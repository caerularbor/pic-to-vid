"""
Local web server for pic-to-vid.

Run it, then open http://127.0.0.1:8000 in your browser. The page uploads a
picture (and optionally a video); this server runs the frame pipeline in a
background thread and reports progress back to the page.

    python server.py
"""

import glob
import importlib.util
import json
import os
import random
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import config

BASE_DIR = config.BASE_DIR
HOST = config.HOST
PORT = config.PORT
HTML_FILE = config.HTML_FILE
UPLOAD_DIR = config.UPLOAD_DIR
FRAMES_DIR = config.FRAMES_DIR
RESULT_VIDEO = config.RESULT_VIDEO

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _load_module(name, rel_path):
    """Import a module whose filename contains a space."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE_DIR, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VID_FMT = _load_module("vid_formatting", "vid formatting.py")
FRAME_CMP = _load_module("frame_comparison", "frame comparison.py")

# --- shared progress state -------------------------------------------------
LOCK = threading.Lock()
STATE = {
    "running": False,
    "stage": "idle",      # idle | extracting | rebuilding | encoding | done | error
    "done": 0,
    "total": 0,
    "remaining": 0,
    "percent": 0.0,
    "message": "",
}


def set_progress(stage, done, total, message):
    with LOCK:
        STATE["stage"] = stage
        STATE["done"] = done
        STATE["total"] = total
        STATE["remaining"] = max(0, total - done)
        STATE["percent"] = round(100.0 * done / total, 1) if total else 0.0
        STATE["message"] = message


def get_progress():
    with LOCK:
        p = dict(STATE)
    p["finished"] = p["stage"] == "done"
    p["error"] = p["stage"] == "error"
    return p


def conversion_worker(image_path, block_size):
    total_holder = [0]
    try:
        # 1) Extract the source video frames once (skip if already done).
        if not glob.glob(os.path.join(FRAMES_DIR, "*")):
            def extract_cb(done, total):
                total_holder[0] = total
                set_progress("extracting", done, total, "Extracting frames…")
            VID_FMT.format_video(progress_cb=extract_cb)

        # 2) Rebuild every frame from the picture tiles, then encode.
        total = len(sorted(glob.glob(os.path.join(FRAMES_DIR, "*"))))
        total_holder[0] = total
        set_progress("rebuilding", 0, total, "Rebuilding frames…")

        def rebuild_cb(done, total):
            total_holder[0] = total
            if done >= total:
                set_progress("encoding", done, total, "Encoding video…")
            else:
                set_progress("rebuilding", done, total, "Rebuilding frames…")

        FRAME_CMP.convert(
            image_path,
            frames_dir=FRAMES_DIR,
            video_path=RESULT_VIDEO,
            block_size=block_size,
            progress_cb=rebuild_cb,
        )

        set_progress("done", total_holder[0], total_holder[0], "Complete")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the page
        set_progress("error", 0, 0, f"Error: {exc}")
    finally:
        with LOCK:
            STATE["running"] = False


def _image_ext(content_type):
    """Map a Content-Type to an image file extension (default .png)."""
    ctype = (content_type or "").lower()
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "png" in ctype:
        return ".png"
    if "gif" in ctype:
        return ".gif"
    if "webp" in ctype:
        return ".webp"
    if "bmp" in ctype:
        return ".bmp"
    return ".png"


def _extract_worker(video_path, replace):
    """Extract frames from a video in a background thread."""
    def run():
        try:
            if replace:
                shutil.rmtree(FRAMES_DIR, ignore_errors=True)

            def extract_cb(done, total):
                set_progress("extracting", done, total, "Extracting frames…")
            VID_FMT.format_video(video_path=video_path, output_dir=FRAMES_DIR,
                                 progress_cb=extract_cb)
            set_progress("idle", 0, 0, "")
        except Exception as exc:  # noqa: BLE001 - surface failure to the page
            set_progress("error", 0, 0, f"Error: {exc}")
        finally:
            with LOCK:
                STATE["running"] = False

    threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "BadAppleConverter/1.0"
    protocol_version = "HTTP/1.1"  # keep-alive: smoother video streaming/buffering

    def log_message(self, fmt, *args):  # quieter logs
        print("[server]", fmt % args, flush=True)

    # ---- helpers ----------------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _resolve(self, url_path):
        """Map a URL path to a safe file path under BASE_DIR."""
        rel = url_path.lstrip("/")
        if rel in ("", "/"):
            rel = HTML_FILE
        full = os.path.normpath(os.path.join(BASE_DIR, rel))
        base = os.path.normpath(BASE_DIR)
        if full != base and not full.startswith(base + os.sep):
            return None
        return full

    def _serve_file(self, full_path, content_type):
        try:
            size = os.path.getsize(full_path)
        except OSError:
            self.send_error(404, "Not found")
            return

        # Basic HTTP Range support so <video> can seek/stream.
        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                start_s, end_s = m.groups()
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(full_path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(end - start + 1))
                return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        if content_type.startswith("text/html"):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(full_path, "rb") as f:
            self.wfile.write(f.read())

    # ---- request handlers -------------------------------------------------
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/progress":
            self._send_json(get_progress())
            return
        if path == "/api/random-frame":
            frames = glob.glob(os.path.join(FRAMES_DIR, "*.jpg"))
            if frames:
                rel = os.path.relpath(random.choice(frames), BASE_DIR).replace("\\", "/")
                self._send_json({"url": "/" + rel})
            else:
                self._send_json({"url": None})
            return
        full = self._resolve(path)
        if full is None or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ext = os.path.splitext(full)[1].lower()
        self._serve_file(full, CONTENT_TYPES.get(ext, "application/octet-stream"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path not in ("/api/convert", "/api/video"):
            self.send_error(404, "Not found")
            return

        print(f"[POST] {path}  Content-Length={self.headers.get('Content-Length')} "
              f"Content-Type={self.headers.get('Content-Type')!r}", flush=True)

        # Respond to "Expect: 100-continue" so the browser actually sends the body.
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.send_response_only(100)
            self.end_headers()

        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        print(f"[POST] read {len(data)} bytes", flush=True)
        if not data:
            self._send_json({"error": "No data received"}, 400)
            return

        with LOCK:
            if STATE["running"]:
                self._send_json({"error": "A job is already running"}, 409)
                return
            STATE["running"] = True

        # ---- video upload: extract frames from the user's video ----
        if path == "/api/video":
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            video_path = os.path.join(UPLOAD_DIR, "uploaded_video.mp4")
            with open(video_path, "wb") as f:
                f.write(data)
            print(f"Received video ({len(data)} bytes) -> {video_path}", flush=True)
            set_progress("extracting", 0, 1, "Extracting frames…")
            _extract_worker(video_path, replace=True)
            self._send_json({"started": True})
            return

        # ---- picture upload + conversion ----
        qs = parse_qs(parsed.query)
        try:
            block_size = int(qs.get("block_size", [str(config.BLOCK_SIZE)])[0])
        except (TypeError, ValueError):
            block_size = config.BLOCK_SIZE
        block_size = max(1, min(32, block_size))

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        image_path = os.path.join(UPLOAD_DIR, "uploaded" + _image_ext(self.headers.get("Content-Type", "")))
        with open(image_path, "wb") as f:
            f.write(data)
        print(f"Received image ({len(data)} bytes) -> {image_path} (block {block_size})", flush=True)

        set_progress("rebuilding", 0, 1, "Starting…")
        threading.Thread(target=conversion_worker, args=(image_path, block_size), daemon=True).start()
        self._send_json({"started": True})


def start_extraction():
    """Extract the source video's frames on first start, in the background."""
    if glob.glob(os.path.join(FRAMES_DIR, "*")):
        return  # frames already present

    with LOCK:
        if STATE["running"]:
            return
        STATE["running"] = True

    _extract_worker(config.VIDEO_PATH, replace=False)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    start_extraction()
    print(f"ovo running at http://{HOST}:{PORT}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server…", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
