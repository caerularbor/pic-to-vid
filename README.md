#pic to vid

disclaimer: this was a vibe coded small project for a school hackathon
if you dont like ai coded stuff im sorry me too

---



web tool to convert any picture to any video through mosaic art
picture is parsed into blocks and video is reconstructed purely through those blocks

## instructions
open powershell, then paste in
```powershell
pip install -r requirements.txt   # one time
python "vid formatting.py"        # extract the video into frames (one time per video)
python server.py                  # start the local web page
```

then open **http://127.0.0.1:8000**, drop in a picture, and hit **Convert**.

---

## settings

all settings avaliable in config.py

| Setting | Default | What it does |
|---|---|---|
| `VIDEO_PATH` | the mp4 | the video to convert (change to any video file) |
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

## files

| File | What it is |
|---|---|
| [`config.py`](config.py) | All settings in one place — the only file you normally need to edit. |
| [`server.py`](server.py) | Local web server. Serves the page, receives the uploaded picture, runs the conversion in the background, and reports progress. |
| [`vid formatting.py`](vid formatting.py) | Splits the video into individual frames (JPEGs) into `frames/`, using ffmpeg. |
| [`frame comparison.py`](frame comparison.py) | The core mosaic engine: cuts the picture into blocks, matches each video block to the closest picture block, and encodes the result with ffmpeg. |
| [`requirements.txt`](requirements.txt) | Python dependencies (`opencv-python`, `numpy`, `imageio-ffmpeg`). |

---

##demo

demo uses a small little vid from my friend
sorry dude

