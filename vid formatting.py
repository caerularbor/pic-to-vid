import glob
import os
import subprocess
import threading

import cv2

import config

# ---------------------------------------------------------------------------
# Parse a video file into indexed pictures at TARGET_FPS for the entire video.
# Frames are saved into FRAMES_DIR.
#
# Extraction is done with ffmpeg (multithreaded native decode + JPEG encode)
# instead of a Python read/write loop, which makes the first run far faster.
# Settings come from config.py.
# ---------------------------------------------------------------------------


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _estimate_total(video_path, target_fps):
    """Estimate how many frames the extraction will produce."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS) or target_fps
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return int(count * target_fps / fps) if count and fps else 0


def format_video(video_path=None, output_dir=None, target_fps=None,
                 progress_cb=None):
    """
    Sample `video_path` at `target_fps` and save indexed JPEG frames into
    `output_dir` using ffmpeg. Returns the number of saved frames.

    `progress_cb(done, total)` is called periodically while ffmpeg runs.
    Any argument left as None falls back to the value in config.py.
    """
    video_path = video_path or config.VIDEO_PATH
    output_dir = output_dir or config.FRAMES_DIR
    target_fps = target_fps or config.TARGET_FPS

    os.makedirs(output_dir, exist_ok=True)
    ffmpeg = _ffmpeg_exe()
    total = _estimate_total(video_path, target_fps)

    pattern = os.path.join(output_dir, "frame_%06d.jpg")
    glob_pattern = os.path.join(output_dir, "frame_*.jpg")

    # Video filter: sample at the target fps, then optionally downscale.
    vf = f"fps={target_fps}"
    if config.OUTPUT_WIDTH:
        vf += f",scale={config.OUTPUT_WIDTH}:-2"

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", video_path,
        "-vf", vf,
        "-q:v", str(config.EXTRACT_JPEG_QUALITY),
        "-start_number", "0",
        pattern,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Report progress by polling how many frames have landed on disk so far.
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            if progress_cb:
                done = len(glob.glob(glob_pattern))
                progress_cb(done, max(total, done))
            stop.wait(0.15)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()

    stderr_text = proc.stderr.read()  # small (loglevel error); returns at EOF
    proc.wait()
    stop.set()
    poller.join(timeout=1)

    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg extraction failed: " + stderr_text.decode(errors="replace")[:2000]
        )

    saved = len(glob.glob(glob_pattern))
    if progress_cb:
        progress_cb(saved, max(saved, total))
    return saved


def _print_progress(done, total):
    print(f"Extracted {done} frames (~{total} total)", flush=True)


if __name__ == "__main__":
    saved = format_video(progress_cb=_print_progress)
    print(f"Done. Saved {saved} frames to '{config.FRAMES_DIR}' at {config.TARGET_FPS} fps.",
          flush=True)
