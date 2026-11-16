# Smart CCTV: Real-Time Perimeter Intrusion and Crime Detection using VLLMs

A FastAPI service that analyses CCTV video, detects people/vehicles, tracks them,
raises a trigger when something enters a restricted zone, and sends the buffered
clip to a Vision-Language Model (Google Gemini) which classifies the event
(normal / intrusion / theft / assault / robbery / vandalism / other) with a
severity score. Serious events (severity >= 3) become alerts on a live dashboard.

## Pipeline

```
video -> YOLOv8 detection -> ByteTrack tracking -> zone-breach trigger
      -> clip (4 s before + 2 s after trigger) -> 6 key frames -> Gemini (JSON) -> alert engine
      -> REST API + WebSocket -> dashboard
```

## Modules

| File | Role |
|---|---|
| `config.py` | All settings: model names, restricted-zone polygon, buffer length, severity threshold |
| `detection.py` | YOLOv8 person/vehicle detection; `Zone` polygon test using each object's foot point |
| `tracking.py` | ByteTrack IDs; `ZoneMonitor` fires a breach when an object stays in the zone for 3+ frames (re-checked every 15 s while it lingers, 10 s global cooldown); clip = 4 s before + 2 s after the trigger |
| `vlm.py` | Picks key frames, calls Gemini with a structured-output schema, returns `{event_type, severity, description, confidence}` |
| `alerts.py` | Creates alert records (timestamp, type, severity, description, snapshot, source video) when severity >= 3; stores them in `data/alerts.json` |
| `streams.py` | Live input: reader thread (always keeps only the newest frame), processing thread (~10 fps through the same pipeline), automatic reconnect |
| `scripts/demo_playwright.py` | Playwright script that drives the dashboard in a visible browser for demos |
| `scripts/simulate_rtsp.py` | Fake IP camera for demos: loops a video file as an RTSP stream on this computer |
| `main.py` | FastAPI app: upload, background processing queue, alert endpoints, WebSocket |
| `templates/dashboard.html` | Single-page dashboard (plain HTML/JS, no framework) |

## Setup

Requires Python 3.10+. An NVIDIA GPU is optional (it speeds up YOLO a lot).

```
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124   # or CPU build
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.5-flash
```

## Run

```
uvicorn main:app --port 8000
```

Open http://127.0.0.1:8000, choose a video, and click **Upload & analyse**. Alerts
appear as colour-coded cards as Gemini returns results.

Test each stage on its own:

```
python detection.py data/videos/Assault001_x264.mp4   # boxes + zone  -> data/detect_demo.mp4
python tracking.py  data/videos/Assault001_x264.mp4   # IDs + breaches -> data/track_demo.mp4
python vlm.py       data/videos/Assault001_x264.mp4   # Gemini classification printed
```

## API

| Endpoint | Description |
|---|---|
| `POST /upload` | Upload a video (multipart `file`, optional `zone`: `default`, `full` for whole frame, or a JSON list of `[x,y]` points in 0-1); returns a `job_id` |
| `POST /streams` | Start continuous analysis of a live camera. JSON body: `{"url": "rtsp://...", "name": "Gate", "zone": "default"}` (url may also be `http(s)://...` or a webcam number such as `0`) |
| `GET /streams` | List live streams with status (`connecting` / `live` / `reconnecting` / `stopped`), fps, counts |
| `DELETE /streams/{id}` | Stop a live stream |
| `GET /alerts?severity=&min_severity=&event_type=` | List alerts, newest first |
| `GET /alerts/poll?after=<alert_id>` | Polling feed: alerts newer than the given id |
| `DELETE /alerts` | Clear all alerts |
| `GET /status` | Active job count, per-job progress, every VLM analysis (incl. below-threshold ones), total alerts |
| `WS /ws/alerts` | Live push of each new alert |
| `GET /docs` | Interactive Swagger UI |

## Live camera (RTSP) input

Besides uploaded files, the system can watch a live camera continuously. It runs the
exact same pipeline (detection -> tracking -> zone trigger -> Gemini -> alert).

**Demo without hardware** - simulate an IP camera on this computer (needs internet the
first time, to download the small open-source RTSP server MediaMTX; the download is
verified against its published checksum):

```
# terminal 1: the fake camera (leave running)
python scripts/simulate_rtsp.py data/videos/Assault001_x264.mp4
#   -> rtsp://127.0.0.1:8554/cam1

# terminal 2: the app
uvicorn main:app --port 8000
```

Then in the dashboard, under **Connect a live camera**, enter `rtsp://127.0.0.1:8554/cam1`
and press **Start live analysis** (or `curl -X POST http://127.0.0.1:8000/streams -H "Content-Type: application/json" -d "{\"url\":\"rtsp://127.0.0.1:8554/cam1\"}"`).
A laptop webcam also works: use `0` as the URL.

To start a camera automatically whenever the server starts, add `RTSP_URL=rtsp://...` to `.env`.

### Automated demo in a visible browser

With the fake camera running, this opens the dashboard in Edge and demos both modes
(file upload, then the live RTSP stream), printing a plain-English line at each step:

```
python scripts/demo_playwright.py              # --mode upload | live, --slow-mo 1200, --live-seconds 180
```

### Connecting a real CCTV camera (for the report)

An IP camera is a small computer that publishes its video on the local network. RTSP
(Real Time Streaming Protocol) is the common "address" format for that video, so
connecting the project to a camera only means giving it that address:

1. Put the camera and the computer running this project on the same network.
2. Find the camera's RTSP address: it is in the camera's manual or web settings, or on the
   manufacturer's list. It looks like `rtsp://username:password@192.168.1.64:554/stream1`
   (the IP address, port and path differ per brand; e.g. Hikvision uses `/Streaming/Channels/101`).
   Create a dedicated read-only camera user instead of using the admin account.
3. Check it first in VLC (Media > Open Network Stream). If VLC shows video, this project can read it.
4. Paste the address into the dashboard (or `POST /streams`). The camera's password is hidden
   in the dashboard and in API responses.
5. Choose the restricted zone for that camera's view. Every camera sees a different scene,
   so the zone must be set per camera (custom polygon via the API, coordinates between 0 and 1).

If the camera loses power or the network drops, the system shows `reconnecting` and
resumes by itself. If Gemini is slow, new breaches are skipped (counted as "skipped") rather
than queued forever, so the feed never falls behind real time. Because a live feed is
processed at about 10 frames per second, the load stays modest even on a laptop GPU.

## Restricted zone

The dashboard offers the default zone or the whole frame per upload; the API also accepts a custom polygon. To change the default, edit `DEFAULT_ZONE` in `config.py`: a list of `(x, y)` points as fractions of the
frame (0-1), so it works at any resolution.

## Models and data

- **Detection/tracking:** YOLOv8s pretrained on COCO (Ultralytics) with the built-in ByteTrack tracker. Classes: person, bicycle, car, motorcycle, bus, truck.
- **VLM:** Google Gemini (`gemini-3.5-flash`) via the `google-genai` SDK, using JSON-schema structured output.
- **Test footage:** a small sample of the **UCF-Crime** dataset (Kaggle `mission-ai/crimeucfdataset`): Assault, Arson, Burglary, Fighting and Normal videos. The **ShanghaiTech Campus** dataset (`nikanvasei/shanghaitech-campus-dataset`) was accessed via the Kaggle API but is stored as JPEG frame sequences rather than video; it has not been used in testing yet.

## Results on sample videos

| Video | Zone | Breaches | Alerts | Outcome |
|---|---|---|---|---|
| UCF Assault001 | default | 8 | 5 | assault, severity 4 |
| UCF Burglary001 | default | 5 | 5 | intrusion / theft / vandalism (vehicle through shopfront), severity 4 |
| UCF Normal_Videos_003 | default | 0 | 0 | correctly quiet |
| ShanghaiTech 01_0014 (150 frames) | whole frame | 1 | 0 | normal footage, no false alarm |
| UCF Fighting002 | whole frame | 3 | 0 | Gemini rated bar scenes severity 1-2; the fight itself was not caught |

(Small sample, not a formal benchmark.)

## Limitations

- UCF-Crime footage is low resolution (320x240), so YOLO sometimes misses or mislabels objects.
- Triggers only fire on restricted-zone entry, so crimes outside the zone are not analysed.
- The VLM sees about 6 still frames, not full motion, and can misjudge ambiguous scenes.
- Detection depends on the zone: if the action happens outside it (as in Fighting002), nothing is analysed. Zones should be set per camera.
- Gemini can be overloaded (503); the app retries and falls back across models, but a clip can still fail (shown in `/status` errors).
- Live streams: each loads its own YOLO model (max 2 at once). Only video is used (no audio), and alert timestamps for live streams are seconds since the stream started.
- Jobs are processed one at a time; alerts live in a JSON file (not a database).
