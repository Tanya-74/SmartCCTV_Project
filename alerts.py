"""Step 4 - Alert engine: turns VLM results into stored alert records.

An alert is created only when severity >= config.ALERT_MIN_SEVERITY.
Alerts are kept in memory for fast listing and persisted to data/alerts.json
(snapshot images go in data/alerts/).
"""
from __future__ import annotations
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

import cv2

import config

DB_FILE = config.DATA_DIR / "alerts.json"


class AlertStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.alerts: list[dict] = []
        if DB_FILE.exists():
            try:
                self.alerts = json.loads(DB_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.alerts = []

    def _save(self):
        DB_FILE.write_text(json.dumps(self.alerts, indent=1), encoding="utf-8")

    def maybe_create(self, result, snapshot, source_video: str, video_time_sec: float) -> dict | None:
        """result: vlm.Classification. Returns the alert dict, or None if below threshold."""
        if result.severity < config.ALERT_MIN_SEVERITY or result.event_type == "normal":
            return None
        aid = uuid.uuid4().hex[:10]
        snap_name = f"{aid}.jpg"
        cv2.imwrite(str(config.ALERT_DIR / snap_name), snapshot)
        alert = {
            "id": aid,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "video_time_sec": round(video_time_sec, 1),
            "event_type": result.event_type,
            "severity": result.severity,
            "confidence": result.confidence,
            "description": result.description,
            "snapshot": f"/alert-images/{snap_name}",
            "source_video": source_video,
        }
        with self._lock:
            self.alerts.append(alert)
            self._save()
        return alert

    def list(self, severity: int | None = None, event_type: str | None = None, min_severity: int | None = None):
        with self._lock:
            out = list(self.alerts)
        if severity is not None:
            out = [a for a in out if a["severity"] == severity]
        if min_severity is not None:
            out = [a for a in out if a["severity"] >= min_severity]
        if event_type:
            out = [a for a in out if a["event_type"] == event_type]
        return sorted(out, key=lambda a: a["timestamp"], reverse=True)

    def since(self, last_id: str | None):
        """Alerts created after the alert with id=last_id (oldest first) - used for live polling."""
        with self._lock:
            items = list(self.alerts)
        if last_id:
            ids = [a["id"] for a in items]
            if last_id in ids:
                items = items[ids.index(last_id) + 1:]
        return items

    def clear(self):
        with self._lock:
            self.alerts = []
            self._save()
