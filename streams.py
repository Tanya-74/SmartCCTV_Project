"""Live-stream input (RTSP IP cameras, HTTP streams, USB webcams).

A LiveStream runs two threads:
  * reader    - pulls frames from the camera as fast as they arrive and keeps ONLY the
                newest one, so a slow detector never makes the feed lag behind real time;
  * processor - takes the newest frame ~LIVE_FPS times per second and runs the same
                detection -> tracking -> zone-breach pipeline used for uploaded files.
If the connection drops it reconnects automatically (waiting longer after each failure).
"""
from __future__ import annotations
import os
import threading
import time
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import cv2

import config
from detection import Detector, Zone
from tracking import ZoneMonitor

# TCP is far more reliable than UDP for RTSP over Wi-Fi/LAN (no dropped-packet smearing).
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

ALLOWED_SCHEMES = ("rtsp", "rtsps", "http", "https")


def validate_source(source: str):
    """Returns the value to hand to OpenCV: a URL string, or an int for a webcam index."""
    s = (source or "").strip()
    if s.isdigit():
        return int(s)
    if urlsplit(s).scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError("source must be an rtsp://, rtsps://, http(s):// URL or a webcam number like 0")
    return s


def mask_source(source) -> str:
    """Hide any password in rtsp://user:password@host/... before showing it anywhere."""
    if isinstance(source, int):
        return f"webcam {source}"
    p = urlsplit(source)
    if p.password:
        netloc = f"{p.username}:***@{p.hostname}" + (f":{p.port}" if p.port else "")
        return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    return source


class LiveStream:
    def __init__(self, job: dict, source, zone_points, on_breach: Callable):
        """job: the shared status dict (also shown by /status). on_breach(job, breach, fps)."""
        self.job = job
        self.source = source                      # real URL (may hold a password) - never exposed
        self.zone = Zone(zone_points)
        self.on_breach = on_breach
        self.stop_event = threading.Event()
        self.detector = Detector()                # own model + tracker state per stream
        self._lock = threading.Lock()
        self._latest = None
        self._seq = 0
        self._connected = False
        self.threads = [threading.Thread(target=self._read_loop, daemon=True),
                        threading.Thread(target=self._process_loop, daemon=True)]

    # ---- lifecycle ----
    def start(self):
        self.job["status"] = "connecting"
        for t in self.threads:
            t.start()

    def stop(self):
        self.stop_event.set()

    def _set(self, status: str):
        if self.job["status"] != "stopped":
            self.job["status"] = status

    # ---- reader thread ----
    def _open(self):
        if isinstance(self.source, int):
            return cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        # timeouts must be given at open time, otherwise a dead camera blocks for ~30 s
        return cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000])

    def _read_loop(self):
        delay = 2
        while not self.stop_event.is_set():
            cap = self._open()
            if not cap.isOpened():
                self._connected = False
                self._set("reconnecting")
                self._note_error(f"cannot connect to {mask_source(self.source)}; retrying in {delay}s")
                cap.release()
                self.stop_event.wait(delay)
                delay = min(delay * 2, 30)
                continue
            delay = 2
            self._connected = True
            self._set("live")
            fails = 0
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    fails += 1
                    if fails >= 5:          # stream really dropped (not just one bad packet)
                        break
                    continue
                fails = 0
                with self._lock:
                    self._latest, self._seq = frame, self._seq + 1
            cap.release()
            self._connected = False
            if not self.stop_event.is_set():
                self._set("reconnecting")
                self._note_error("stream interrupted; reconnecting")
                self.stop_event.wait(2)
        self._connected = False

    # ---- processing thread ----
    def _process_loop(self):
        fps = config.LIVE_FPS
        interval = 1.0 / fps
        monitor, last_seq, t0, window = None, -1, None, []
        try:
            while not self.stop_event.is_set():
                with self._lock:
                    frame, seq = self._latest, self._seq
                if frame is None or seq == last_seq or not self._connected:
                    if not self._connected:
                        monitor, last_seq = None, -1      # fresh tracker after a reconnect
                    self.stop_event.wait(0.02)
                    continue
                last_seq = seq
                if monitor is None:
                    monitor, t0 = ZoneMonitor(self.detector, self.zone, fps), time.time()
                started = time.time()
                _, breach = monitor.process(frame)
                self.job["frames_processed"] += 1
                if breach:
                    breach.timestamp_sec = time.time() - self.job["started_at"]
                    self.job["breaches"] += 1
                    self.on_breach(self.job, breach, fps)
                window.append(time.time())
                window = [w for w in window if w > window[-1] - 5]
                if len(window) > 1:
                    self.job["fps"] = round((len(window) - 1) / (window[-1] - window[0]), 1)
                # throttle to LIVE_FPS (skipped frames are simply never processed)
                self.stop_event.wait(max(0.0, interval - (time.time() - started)))
        except Exception as e:
            self._note_error(f"processing error: {e}")
            self.job["status"] = "error"
            self.stop_event.set()
        finally:
            if self.job["status"] != "error":
                self.job["status"] = "stopped"
            self.job["finished_at"] = time.time()

    def _note_error(self, msg: str):
        errs = self.job["errors"]
        if not errs or errs[-1] != msg:
            errs.append(msg[:200])
            del errs[:-5]                 # keep only the 5 most recent
