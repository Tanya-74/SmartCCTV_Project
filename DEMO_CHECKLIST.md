# Demo checklist (evaluation day)

## The night before (internet ON)
1. Start the server and warm it up, so the dashboard already holds real alerts as a backup:
   ```
   .venv\Scripts\python.exe -m uvicorn main:app --port 8000
   ```
   Open http://127.0.0.1:8000, upload `data/videos/Assault001_x264.mp4` and `Burglary001_x264.mp4`, wait for alerts.
   Alerts are saved in `data/alerts.json`, so they are still there after a restart, even with no internet.
2. Optional: run the browser demo once: `python scripts\demo_playwright.py` (needs the fake camera: `python scripts\simulate_rtsp.py` in another terminal).
3. Rebuild the report/slides if you edit anything: `python scripts\evaluate_baselines.py`, `python scripts\build_report.py`, `powershell -File scripts\build_slides.ps1`.

## What works with the internet OFF (tested on this laptop)
| Part | Offline? |
|---|---|
| Server start, dashboard page, previously saved alerts | Yes |
| YOLO detection, tracking, zone breach detection on an uploaded video | Yes |
| Fake RTSP camera (MediaMTX + ffmpeg, both already downloaded in `tools/`) | Yes |
| Coordinate Descent / baselines (`python scripts\tune_coordinate_descent.py`, `python scripts\evaluate_baselines.py`) | Yes - they read the cached Gemini answers |
| Gemini classification of new clips (the part that creates alerts) | **No** - needs internet + API key |

When tested with the network down, an upload was accepted and detection ran, but Gemini calls failed and no alert was created. Failed calls are retried for a few minutes, so do not wait on it live.

**So: if the internet is down in the room, show the saved alerts on the dashboard, run the offline scripts, and explain that classification needs the cloud model.** Say it plainly; it is a known limitation in the report (section 10).

## Screen sharing safely
- Share a single window (the browser with the dashboard), not the whole screen.
- Do not open `.env` or any editor tab showing the Gemini key. Close VS Code or keep it out of the shared window.
- Run the server in a terminal you are not sharing; turn on Do Not Disturb so notifications do not pop up.
- Have the slides open in a second window and the report PDF ready: `report/Final_Presentation.pptx`, `report/Final_Project_Report.pdf`.

## Likely questions (short honest answers)
- *Did you train a model?* No. YOLOv8 and Gemini are pretrained. Our work is the pipeline, the decision rule, the tuning experiment and the evaluation.
- *Did it beat the baseline?* It beat always-alert (0.857 vs 0.800), not zone-breach-only (0.857 vs 0.889). The gap is one video.
- *Why did you not use the tuned parameters?* 6 videos, tuned and scored on the same data, 922 tied settings. Not trustworthy.
- *Why did it miss Fighting002?* The zone-entry trigger probably never sent the fight itself to Gemini.
- *Does it work offline?* Detection yes, classification no.
