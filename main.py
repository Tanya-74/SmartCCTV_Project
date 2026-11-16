"""FastAPI backend: upload videos, run the detection->tracking->VLM->alert pipeline,
serve alerts and the dashboard.

Run:  uvicorn main:app --reload   then open http://127.0.0.1:8000
"""
from __future__ import annotations
import asyncio
import json
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config
from alerts import AlertStore
from detection import Detector, Zone
from tracking import ZoneMonitor
from streams import LiveStream, mask_source, validate_source
from vlm import VLMClassifier

app = FastAPI(title="Smart CCTV")
app.mount("/alert-images", StaticFiles(directory=str(config.ALERT_DIR)), name="alert-images")
templates = Jinja2Templates(directory=str(config.ROOT / "templates"))

store = AlertStore()
detector = Detector()          # loaded once, shared (jobs run one at a time)
_vlm: VLMClassifier | None = None
jobs: dict[str, dict] = {}
job_queue: Queue = Queue()
ws_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None
vlm_pool = ThreadPoolExecutor(max_workers=2)
live_streams: dict[str, LiveStream] = {}
_pend_lock = threading.Lock()


def parse_zone(spec: str):
    spec = (spec or "default").strip()
    if spec == "default":
        return config.DEFAULT_ZONE
    if spec == "full":
        return [(0, 0), (1, 0), (1, 1), (0, 1)]
    try:
        pts = [(float(x), float(y)) for x, y in json.loads(spec)]
        assert len(pts) >= 3 and all(0 <= v <= 1 for p in pts for v in p)
    except Exception:
        raise ValueError("zone must be 'default', 'full', or a JSON list of at least 3 [x,y] points, each between 0 and 1")
    return pts


def _pend(job: dict, delta: int):
    with _pend_lock:
        job["pending_vlm"] += delta


def get_vlm() -> VLMClassifier:
    global _vlm
    if _vlm is None:
        _vlm = VLMClassifier()
    return _vlm


def _broadcast(alert: dict):
    if _loop is None:
        return
    for ws in list(ws_clients):
        asyncio.run_coroutine_threadsafe(_safe_send(ws, alert), _loop)


async def _safe_send(ws: WebSocket, alert: dict):
    try:
        await ws.send_json(alert)
    except Exception:
        ws_clients.discard(ws)


def _classify_and_alert(job: dict, breach, fps: float):
    """Runs in a worker thread so video processing is not blocked by the VLM."""
    try:
        res = get_vlm().classify(breach.frames, who=", ".join(sorted(set(breach.labels))),
                                 clip_seconds=len(breach.frames) / fps)
        job["breaches_classified"] += 1
        job["analyses"].append({"t": round(breach.timestamp_sec, 1), "event_type": res.event_type,
                                 "severity": res.severity, "description": res.description})
        del job["analyses"][:-50]
        alert = store.maybe_create(res, breach.annotated_frame, job["filename"], breach.timestamp_sec)
        if alert:
            job["alerts_created"] += 1
            _broadcast(alert)
    except Exception as e:
        job["errors"].append(str(e)[:200])
        del job["errors"][:-5]
    finally:
        _pend(job, -1)


def process_video(job_id: str):
    job = jobs[job_id]
    job["status"] = "processing"
    cap = cv2.VideoCapture(job["path"])
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    mon = ZoneMonitor(detector, Zone(job["zone"]), fps)
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            _, breach = mon.process(frame)
            if breach:
                job["breaches"] += 1
                _pend(job, 1)
                vlm_pool.submit(_classify_and_alert, job, breach, fps)
            n += 1
            if n % 15 == 0:
                job["progress"] = round(n / total * 100, 1)
        tail = mon.flush()               # breach near the end of the video
        if tail:
            job["breaches"] += 1
            _pend(job, 1)
            vlm_pool.submit(_classify_and_alert, job, tail, fps)
        job["progress"] = 100.0
        while job["pending_vlm"] > 0:      # wait for Gemini answers
            time.sleep(0.5)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["errors"].append(str(e)[:200])
    finally:
        cap.release()
        job["finished_at"] = time.time()


def worker():
    while True:
        job_id = job_queue.get()
        process_video(job_id)


@app.on_event("startup")
async def startup():
    global _loop
    _loop = asyncio.get_running_loop()
    threading.Thread(target=worker, daemon=True).start()
    if config.RTSP_URL:                      # optional auto-start from .env: RTSP_URL=rtsp://...
        try:
            start_stream(config.RTSP_URL, "LIVE (from .env)", "default")
        except Exception as e:
            print(f"RTSP_URL auto-start failed: {e}")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.post("/upload")
async def upload(file: UploadFile = File(...), zone: str = Form("default")):
    """zone: 'default' | 'full' (whole frame) | JSON list of [x,y] points, 0-1 normalised."""
    if not file.filename.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".webm")):
        raise HTTPException(400, "Please upload a video file (mp4/avi/mov/mkv/webm).")
    try:
        zone_pts = parse_zone(zone)
    except Exception:
        raise HTTPException(400, "zone must be 'default', 'full', or a JSON list of [x,y] points (0-1).")
    job_id = uuid.uuid4().hex[:8]
    path = config.UPLOAD_DIR / f"{job_id}_{file.filename}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    jobs[job_id] = {"id": job_id, "filename": file.filename, "path": str(path), "status": "queued",
                    "progress": 0.0, "breaches": 0, "breaches_classified": 0, "alerts_created": 0,
                    "pending_vlm": 0, "errors": [], "analyses": [], "zone": zone_pts, "started_at": time.time()}
    job_queue.put(job_id)
    return {"job_id": job_id, "status": "queued"}


class StreamRequest(BaseModel):
    url: str                      # rtsp://..., http(s)://... or a webcam number such as "0"
    name: str | None = None       # label shown on the dashboard / in alerts
    zone: str = "default"         # same options as /upload


def _live_breach(job: dict, breach, fps: float):
    """Called by a LiveStream for each breach. Skips it if Gemini is already far behind."""
    if job["pending_vlm"] >= config.MAX_PENDING_VLM:
        job["skipped"] += 1
        return
    _pend(job, 1)
    vlm_pool.submit(_classify_and_alert, job, breach, fps)


def start_stream(url: str, name: str | None, zone: str) -> dict:
    source = validate_source(url)                       # ValueError if not a camera URL
    zone_pts = parse_zone(zone)
    running = [s for s in live_streams.values() if s.job["status"] not in ("stopped", "error")]
    if len(running) >= config.MAX_STREAMS:
        raise RuntimeError(f"Maximum of {config.MAX_STREAMS} live streams already running - stop one first.")
    sid = uuid.uuid4().hex[:8]
    label = name or f"LIVE {mask_source(source)}"
    job = {"id": sid, "kind": "stream", "filename": label, "source": mask_source(source),
           "status": "connecting", "progress": 0.0, "breaches": 0, "breaches_classified": 0,
           "alerts_created": 0, "pending_vlm": 0, "skipped": 0, "frames_processed": 0, "fps": 0.0,
           "errors": [], "analyses": [], "zone": zone_pts, "started_at": time.time()}
    jobs[sid] = job
    stream = LiveStream(job, source, zone_pts, _live_breach)
    live_streams[sid] = stream
    stream.start()
    return job


@app.post("/streams")
async def add_stream(req: StreamRequest):
    """Start continuous analysis of a live camera feed."""
    try:
        job = start_stream(req.url, req.name, req.zone)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"stream_id": job["id"], "status": job["status"], "source": job["source"]}


@app.get("/streams")
async def list_streams():
    return [{k: v for k, v in s.job.items() if k != "zone"} for s in live_streams.values()]


@app.delete("/streams/{stream_id}")
async def stop_stream(stream_id: str):
    s = live_streams.get(stream_id)
    if not s:
        raise HTTPException(404, "No such stream")
    s.stop()
    return {"stream_id": stream_id, "status": "stopping"}


@app.get("/alerts")
async def list_alerts(severity: int | None = None, min_severity: int | None = None, event_type: str | None = None):
    return store.list(severity=severity, min_severity=min_severity, event_type=event_type)


@app.get("/alerts/poll")
async def poll_alerts(after: str | None = None):
    """Polling fallback for the live feed: returns alerts newer than the given alert id."""
    return store.since(after)


@app.delete("/alerts")
async def clear_alerts():
    store.clear()
    return {"cleared": True}


@app.get("/status")
async def status():
    active = [j for j in jobs.values() if j["status"] in ("queued", "processing")]
    live = [j for j in jobs.values() if j.get("kind") == "stream" and j["status"] in ("connecting", "live", "reconnecting")]
    return {"active_jobs": len(active), "active_streams": len(live), "total_alerts": len(store.alerts),
            "jobs": sorted(({k: v for k, v in j.items() if k not in ("path", "zone")} for j in jobs.values()),
                           key=lambda j: j["started_at"], reverse=True)[:10]}


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # keep-alive
    except WebSocketDisconnect:
        ws_clients.discard(ws)
