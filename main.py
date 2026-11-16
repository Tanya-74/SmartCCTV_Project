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

import config
from alerts import AlertStore
from detection import Detector, Zone
from tracking import ZoneMonitor
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


def parse_zone(spec: str):
    spec = (spec or "default").strip()
    if spec == "default":
        return config.DEFAULT_ZONE
    if spec == "full":
        return [(0, 0), (1, 0), (1, 1), (0, 1)]
    pts = [(float(x), float(y)) for x, y in json.loads(spec)]
    if len(pts) < 3 or any(not (0 <= v <= 1) for p in pts for v in p):
        raise ValueError
    return pts


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
        alert = store.maybe_create(res, breach.annotated_frame, job["filename"], breach.timestamp_sec)
        if alert:
            job["alerts_created"] += 1
            _broadcast(alert)
    except Exception as e:
        job["errors"].append(str(e)[:200])
    finally:
        job["pending_vlm"] -= 1


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
                job["pending_vlm"] += 1
                vlm_pool.submit(_classify_and_alert, job, breach, fps)
            n += 1
            if n % 15 == 0:
                job["progress"] = round(n / total * 100, 1)
        tail = mon.flush()               # breach near the end of the video
        if tail:
            job["breaches"] += 1
            job["pending_vlm"] += 1
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
    return {"active_jobs": len(active), "total_alerts": len(store.alerts),
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
