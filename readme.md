# Bad Apple Converter

disclaimer: this was a vibe coded small project for a school hackathon
if you dont like ai coded stuff im sorry me too

---

## What it is

A small web tool that turns **any picture** into a **video made out of that picture**.

It works like a photo-mosaic, but for video:

1. You give it a **picture** (any image).
2. You give it a **video** (any video file).
3. It cuts the picture into tiny blocks, then rebuilds every frame of the video using those blocks — each block of the video frame is replaced with the closest-matching block from your picture.

The result: a video where the whole animation is "drawn" using your picture as the paint.

## Quick start

```powershell
pip install -r requirements.txt   # one time
python "vid formatting.py"        # extract the video into frames (one time per video)
python server.py                  # start the local web page
```

Then open **http://127.0.0.1:8000**, drop in a picture, and hit **Convert to Bad Apple**.

---

## Settings

Everything is configured in [`config.py`](config.py). Change a value, then re-run the relevant script.

| Setting | Default | What it does |
|---|---|---|
| `VIDEO_PATH` | the Bad Apple mp4 | the video to convert (change to any video file) |
| `TARGET_FPS` | `60` | frames per second to sample the video at |
| `START_OFFSET_SECONDS` | `30` | start from a random frame within the first N seconds (skips the mostly-black opening) |
| `BLOCK_SIZE` | `12` | pixel size of each mosaic block — smaller = more detail/slower, larger = chunkier/faster |
| `OUTPUT_WIDTH` | `720` | output width in pixels (height auto) — `0` = native resolution |
| `FRAMES_DIR` | `frames` | where extracted frames are cached |
| `EXTRACT_JPEG_QUALITY` | `5` | JPEG quality of the cached frames (2 = best, 31 = worst) |
| `RESULT_VIDEO` | `result.mp4` | output video path |
| `VIDEO_PRESET` | `ultrafast` | H.264 encode speed (ultrafast → veryslow) |
| `VIDEO_CRF` | `26` | output quality (lower = better/larger, higher = smaller) |
| `MAX_WORKERS` | `0` | parallel worker threads (`0` = one per CPU core) |
| `ENABLE_INTRO` | `True` | slide-in intro animation of the picture's blocks |
| `INTRO_FRAMES` | `45` | length of the intro animation |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | web server address |

---

## Files

| File | What it is |
|---|---|
| [`config.py`](config.py) | All settings in one place — the only file you normally need to edit. |
| [`server.py`](server.py) | Local web server. Serves the page, receives the uploaded picture, runs the conversion in the background, and reports progress. |
| [`bad apple converter.html`](bad apple converter.html) | The web UI (neon-styled): drop zone, convert button, progress bar, and video player. |
| [`vid formatting.py`](vid formatting.py) | Splits the video into individual frames (JPEGs) into `frames/`, using ffmpeg. |
| [`frame comparison.py`](frame comparison.py) | The core mosaic engine: cuts the picture into blocks, matches each video block to the closest picture block, and encodes the result with ffmpeg. |
| [`requirements.txt`](requirements.txt) | Python dependencies (`opencv-python`, `numpy`, `imageio-ffmpeg`). |

---

## Why Bad Apple?

**Bad Apple!!** is used as the default example because it's the perfect stress test for this kind of tool: it's a **black-and-white silhouette animation** (so the matching is easy to see), with **fast motion and big scene changes** (so you can tell whether the mosaic is keeping up). It also has a long, mostly-black intro, which is why the converter starts a bit into the video by default.

To use your own video, just change `VIDEO_PATH` in `config.py`, delete the `frames` folder, and re-run `python "vid formatting.py"`.
