"""
Bad Apple frame comparison — fast rebuild + encode.

Workflow:
  1. Cut the picture into 64x64 pixel blocks (saved to a temp folder, deleted
     at the end).
  2. For each formatted 30 fps frame: decode it as grayscale, compute each
     64x64 block's mean luminance, and find the closest picture block via a
     pre-sorted binary-search index (vectorised NumPy).
  3. Stitch the matched blocks back into the frame and stream it straight into
     ffmpeg as raw video (no intermediate JPEG files), producing a browser-
     playable 30 fps H.264 video.
  4. Optionally prepend an intro that slides the picture's blocks into place
     for the first frame.

Optimisations (each removes a bottleneck):
  - Frames are decoded as grayscale only — matching uses luminance, not colour.
  - Matching is O(blocks) via np.searchsorted on a pre-sorted luminance index,
    not the brute-force O(blocks^2 * pixels).
  - Rebuilt frames are piped to ffmpeg as raw BGR, skipping a full
    JPEG-write + JPEG-decode round trip for every frame.
"""

import argparse
import glob
import os
import random
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

import config

BLOCK = config.BLOCK_SIZE
BASE_DIR = config.BASE_DIR
FPS = config.TARGET_FPS
INTRO_FRAMES = config.INTRO_FRAMES


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _make_temp_dir(prefix):
    path = os.path.join(BASE_DIR, f"{prefix}{uuid.uuid4().hex[:10]}")
    os.makedirs(path, exist_ok=False)
    return path


def block_means(gray):
    """Return a (rows, cols) grid of per-64x64-block mean values."""
    h, w = gray.shape
    rows, cols = h // BLOCK, w // BLOCK
    if rows == 0 or cols == 0:
        return np.zeros((0, 0))
    cropped = gray[: rows * BLOCK, : cols * BLOCK]
    return cropped.reshape(rows, BLOCK, cols, BLOCK).mean(axis=(1, 3))


def build_picture_index(image_path):
    """Split the picture into 64x64 tiles and build a luminance lookup index."""
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rows, cols = gray.shape[0] // BLOCK, gray.shape[1] // BLOCK
    if rows == 0 or cols == 0:
        raise ValueError("Image is smaller than 64x64 pixels.")

    tiles = np.asarray(
        [img[r * BLOCK:(r + 1) * BLOCK, c * BLOCK:(c + 1) * BLOCK]
         for r in range(rows) for c in range(cols)],
        dtype=np.uint8,
    )  # (M, 64, 64, 3)

    means = block_means(gray).ravel().astype(np.float32)  # (M,)
    order = np.argsort(means)
    sorted_means = means[order]
    return img, tiles, order, sorted_means


def nearest_tile_indices(query_means, order, sorted_means):
    """For each query mean, return the original tile index with the closest mean."""
    idx = np.searchsorted(sorted_means, query_means)
    left = np.clip(idx - 1, 0, len(sorted_means) - 1)
    right = np.clip(idx, 0, len(sorted_means) - 1)
    closer = np.where(
        np.abs(sorted_means[left] - query_means)
        <= np.abs(sorted_means[right] - query_means),
        left,
        right,
    )
    return order[closer]


def rebuild_frame_from_gray(gray, tiles, order, sorted_means):
    """Return (chosen_grid, rebuilt_frame) for one grayscale frame."""
    means = block_means(gray)
    fr, fc = means.shape
    if fr == 0 or fc == 0:
        return None, None

    chosen_flat = nearest_tile_indices(means.ravel(), order, sorted_means)
    gathered = tiles[chosen_flat]  # (fr*fc, 64, 64, 3)
    rebuilt = (
        gathered.reshape(fr, fc, BLOCK, BLOCK, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(fr * BLOCK, fc * BLOCK, 3)
    )
    return chosen_flat.reshape(fr, fc), rebuilt


def _rebuild_one(args):
    """Rebuild a single frame (used by the worker thread pool)."""
    path, tiles, order, sorted_means = args
    gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    _, rebuilt = rebuild_frame_from_gray(gray, tiles, order, sorted_means)
    return rebuilt


def render_slide_intro(chosen_grid, tiles, duration=INTRO_FRAMES):
    """
    Animate the picture's 64x64 blocks sliding in (left-to-right, staggered)
    until they assemble the first frame's layout. Returns a list of frames.
    """
    fr, fc = chosen_grid.shape
    height, width = fr * BLOCK, fc * BLOCK
    total = fr * fc
    stagger = duration * 0.55

    frames = []
    for k in range(duration):
        canvas = np.zeros((height, width, 3), np.uint8)
        for idx in range(total):
            r, c = divmod(idx, fc)
            delay = stagger * (idx / max(1, total - 1))
            local = (k - delay) / max(1, duration - stagger)
            q = 0.0 if local < 0.0 else (1.0 if local > 1.0 else local)
            ease = 1.0 - (1.0 - q) ** 3  # cubic ease-out
            x = int(round((1.0 - ease) * -(width + BLOCK) + ease * (c * BLOCK)))
            y = r * BLOCK

            tile = tiles[chosen_grid[r, c]]
            x0 = max(0, x)
            x1 = min(width, x + BLOCK)
            if x1 <= x0:
                continue
            canvas[y:y + BLOCK, x0:x1] = tile[:, (x0 - x):(x0 - x) + (x1 - x0)]
        frames.append(canvas)
    return frames


class VideoWriter:
    """Stream raw BGR frames into ffmpeg to encode H.264 (browser-playable)."""

    def __init__(self, video_path, fps=FPS):
        self.video_path = video_path
        self.fps = fps
        self.proc = None

    def _start(self, width, height):
        cmd = [
            _ffmpeg_exe(), "-y", "-hide_banner", "-nostats", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
            "-framerate", str(self.fps), "-i", "-",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", config.VIDEO_PRESET, "-tune", "fastdecode",
            "-crf", str(config.VIDEO_CRF),
            "-movflags", "+faststart",
            self.video_path,
        ]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def write(self, frame):
        if self.proc is None:
            self._start(frame.shape[1], frame.shape[0])
        if self.proc.poll() is not None:
            raise RuntimeError("ffmpeg encoder exited early")
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        if self.proc is None:
            return
        self.proc.stdin.close()
        self.proc.wait()
        if self.proc.returncode != 0:
            raise RuntimeError(f"ffmpeg encoding failed (exit {self.proc.returncode})")


def convert(image_path, frames_dir=None, video_path=None,
            progress_cb=None, intro=None):
    """
    Rebuild every formatted frame from the picture's tiles and encode a
    browser-playable video. `progress_cb(done, total)` is called after each
    rebuilt frame. Returns `video_path`. Any argument left as None falls back
    to the value in config.py.
    """
    frames_dir = frames_dir or config.FRAMES_DIR
    video_path = video_path or config.RESULT_VIDEO
    if intro is None:
        intro = config.ENABLE_INTRO

    image_blocks_dir = _make_temp_dir("image_blocks_")
    try:
        img, tiles, order, sorted_means = build_picture_index(image_path)

        # 1) Optionally dump the picture's blocks into the temp folder (debug
        #    artifact; disabled by default because it's slow with small blocks).
        if config.SAVE_IMAGE_BLOCKS:
            rows, cols = img.shape[0] // BLOCK, img.shape[1] // BLOCK
            for r in range(rows):
                for c in range(cols):
                    cv2.imwrite(
                        os.path.join(image_blocks_dir, f"img_block_{r:04d}_{c:04d}.png"),
                        img[r * BLOCK:(r + 1) * BLOCK, c * BLOCK:(c + 1) * BLOCK],
                    )

        frame_paths = sorted(glob.glob(os.path.join(frames_dir, "*")))
        if not frame_paths:
            raise FileNotFoundError(f"No frames found in: {frames_dir}")

        # Start the output from a random frame within the first N seconds.
        max_start = min(int(config.START_OFFSET_SECONDS * FPS), max(0, len(frame_paths) - 1))
        start_idx = random.randint(0, max_start)
        if start_idx > 0:
            frame_paths = frame_paths[start_idx:]

        total = len(frame_paths)

        writer = VideoWriter(video_path)
        written = 0

        # First frame gives the layout + output dimensions.
        first_gray = cv2.imread(frame_paths[0], cv2.IMREAD_GRAYSCALE)
        chosen0, rebuilt0 = rebuild_frame_from_gray(first_gray, tiles, order, sorted_means)

        # 2) Optional slide-in intro of the picture's blocks into the first frame.
        if intro and chosen0 is not None:
            for intro_frame in render_slide_intro(chosen0, tiles):
                writer.write(intro_frame)

        if rebuilt0 is not None:
            writer.write(rebuilt0)
            written += 1
            if progress_cb:
                progress_cb(written, total)

        # 3) Rebuild the remaining frames in parallel and stream them into ffmpeg.
        rest = frame_paths[1:]
        if rest:
            workers = config.MAX_WORKERS or min(os.cpu_count() or 1, 8)
            args_iter = ((p, tiles, order, sorted_means) for p in rest)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for rebuilt in pool.map(_rebuild_one, args_iter, chunksize=32):
                    if rebuilt is None:
                        continue
                    writer.write(rebuilt)
                    written += 1
                    if progress_cb:
                        progress_cb(written, total)

        writer.close()
        return video_path
    finally:
        shutil.rmtree(image_blocks_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Rebuild Bad Apple frames from picture tiles.")
    parser.add_argument("image", help="path to the uploaded picture")
    parser.add_argument("--frames", default=config.FRAMES_DIR,
                        help="folder containing formatted frames (default from config.py)")
    parser.add_argument("--video", default=config.RESULT_VIDEO,
                        help="output video path (default from config.py)")
    parser.add_argument("--no-intro", action="store_true",
                        help="disable the slide-in intro")
    args = parser.parse_args()

    def progress(done, total):
        if done % 100 == 0 or done == total:
            print(f"Rebuilt {done}/{total} frames ({max(0, total - done)} left)", flush=True)

    convert(args.image, args.frames, args.video, progress, intro=not args.no_intro)
    print(f"Done. Video -> {args.video}", flush=True)


if __name__ == "__main__":
    main()
