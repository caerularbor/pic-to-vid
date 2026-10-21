"""
Central configuration for pic-to-vid.

Edit the values below to reuse the tool on other videos, other resolutions, or
different output settings. Every script reads its settings from here, so you
only need to change things in one place.
"""

import os

# Project root (the folder this file lives in). Everything else is resolved
# relative to this so the scripts work no matter where you run them from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Input video — change this to convert a different video file.
# ---------------------------------------------------------------------------
VIDEO_PATH = os.path.join(
    BASE_DIR,
    "ovo.mp4",
)

# Frames per second to sample the video at. Set this to the video's native
# frame rate (or a clean multiple of it) to avoid judder.
TARGET_FPS = 24

# Start the output from a random frame within the first N seconds of the video
# (0 = always the very first frame). Set 0 to play the whole video from the start.
START_OFFSET_SECONDS = 0

# ---------------------------------------------------------------------------
# Pixel block size for the mosaic. Each video frame is divided into blocks of
# this many pixels and each block is matched against the picture's blocks.
#   * Larger block  -> faster, chunkier result
#   * Smaller block -> more detail, slower
# Must be at least 1. 8 gives a fine mosaic.
# ---------------------------------------------------------------------------
BLOCK_SIZE = 8

# ---------------------------------------------------------------------------
# Frame cache — extracted frames are stored here so extraction only runs once.
# ---------------------------------------------------------------------------
FRAMES_DIR = os.path.join(BASE_DIR, "frames")

# JPEG quality for the cached frames (ffmpeg -q:v scale: 2 = best, 31 = worst).
# 5 keeps the frames folder much smaller at high resolutions with no visible
# effect on matching (only block-average brightness is used).
EXTRACT_JPEG_QUALITY = 5

# Output width in pixels (height is auto-computed to keep aspect ratio).
# Downscaling is faster with little visible loss for a mosaic.
# Set 0 to keep the native resolution.
OUTPUT_WIDTH = 720

# Whether to also dump the picture's individual blocks into a temp folder.
# This is only a debug artifact and is very slow with small block sizes, so it
# is disabled by default.
SAVE_IMAGE_BLOCKS = False

# ---------------------------------------------------------------------------
# Output video.
# ---------------------------------------------------------------------------
RESULT_VIDEO = os.path.join(BASE_DIR, "result.mp4")

# H.264 encoder speed/quality preset:
# ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow.
VIDEO_PRESET = "ultrafast"

# H.264 quality (0 = lossless, 18-23 = visually near-lossless, higher = smaller).
# Higher CRF = lower bitrate = smoother playback on weaker GPUs (the 8x8 mosaic
# is blocky anyway, so a bit more compression is visually fine).
VIDEO_CRF = 26

# Number of parallel worker threads for the rebuild. 0 = auto (one per CPU core).
# Raise/lower this to tune conversion speed on your machine.
MAX_WORKERS = 0

# ---------------------------------------------------------------------------
# Intro animation — slides the picture's blocks into the first frame.
# ---------------------------------------------------------------------------
ENABLE_INTRO = True
INTRO_FRAMES = 45  # intro length in frames (at TARGET_FPS); more = smoother slide

# ---------------------------------------------------------------------------
# Web server.
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8000
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded")
HTML_FILE = "pic to vid.html"  # served at "/" (relative to BASE_DIR)
