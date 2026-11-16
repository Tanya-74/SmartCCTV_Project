"""Shared pieces for the tuning experiment (cache builder + Coordinate Descent).

Everything here is OFFLINE: it replays saved YOLO detections through the real
ZoneTrigger rule and looks up saved Gemini answers. No video or API is needed
once the caches exist.
"""
from __future__ import annotations
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config                                        # noqa: E402
from detection import Detection, Zone                # noqa: E402
from tracking import ZoneTrigger                     # noqa: E402

EXP_DIR = ROOT / "experiments"
EXP_DIR.mkdir(exist_ok=True)
DET_CACHE = EXP_DIR / "detections_cache.json.gz"
GEMINI_CACHE = EXP_DIR / "gemini_cache.json"
VIDEO_DIR = ROOT / "data" / "videos"

LOW_CONF = 0.15        # detections are cached at this (loosest) confidence, then filtered upwards
QUANT_SEC = 3          # breach times are rounded to this grid when matching cached Gemini answers

# The four "coordinates" and the values each may take (the search ranges).
GRIDS = {
    "alert_min_severity":    [1, 2, 3, 4, 5],
    "yolo_conf":             [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65],
    "min_frames_in_zone":    [1, 2, 3, 5, 8, 12, 20, 30],
    "min_gemini_confidence": [0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95],
}
# What the shipped system uses today (min_gemini_confidence 0.0 = "no confidence filter").
DEFAULTS = {
    "alert_min_severity": config.ALERT_MIN_SEVERITY,
    "yolo_conf": config.YOLO_CONF,
    "min_frames_in_zone": 3,
    "min_gemini_confidence": 0.0,
}
ZONES = {"full": [(0, 0), (1, 0), (1, 1), (0, 1)], "default": config.DEFAULT_ZONE}

INCIDENT_PREFIXES = ("Assault", "Burglary", "Arson", "Fighting")


def label_of(video_name: str):
    """Ground truth from the file name: 1 = incident, 0 = normal, None = unknown (skipped)."""
    if video_name.startswith(INCIDENT_PREFIXES):
        return 1
    if video_name.lower().startswith(("normal", "shanghaitech")):
        return 0
    return None


def list_videos() -> list[Path]:
    return sorted(p for p in VIDEO_DIR.glob("*.mp4") if label_of(p.stem) is not None)


# ---------------------------------------------------------------- detection cache
def save_detections(data: dict):
    with gzip.open(DET_CACHE, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def load_detections() -> dict:
    with gzip.open(DET_CACHE, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- Gemini cache
def load_gemini() -> dict:
    return json.loads(GEMINI_CACHE.read_text(encoding="utf-8")) if GEMINI_CACHE.exists() else {}


def save_gemini(cache: dict):
    GEMINI_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")


def clip_key(video: str, frame_idx: int, who: str, fps: float, n_frames: int) -> tuple[str, int]:
    """Round the trigger frame to the QUANT_SEC grid. Returns (cache key, quantised frame)."""
    step = max(1, round(fps * QUANT_SEC))
    q = min(n_frames - 1, round(frame_idx / step) * step)
    return f"{video}|{q}|{who}", q


def clip_range(q: int, fps: float, n_frames: int) -> tuple[int, int]:
    """Frames of the clip for a trigger at frame q: BUFFER_SECONDS before + POST_TRIGGER_SECONDS after,
    exactly what ZoneMonitor would have collected."""
    start = max(0, q - int(fps * config.BUFFER_SECONDS) + 1)
    end = min(n_frames - 1, q + int(fps * config.POST_TRIGGER_SECONDS))
    return start, end


# ---------------------------------------------------------------- breach simulation
class Replay:
    """Replays cached detections through ZoneTrigger for any (conf, min_frames, zone)."""

    def __init__(self, det_cache: dict, zone_name: str = "full"):
        self.cache = det_cache
        self.zone = Zone(ZONES[zone_name])
        self._frames: dict[str, list] = {}       # video -> list (per frame) of Detection, in_zone filled in
        self._memo: dict[tuple, list] = {}

    def _detections(self, video: str) -> list:
        if video not in self._frames:
            v = self.cache[video]
            w, h = v["w"], v["h"]
            frames = []
            for fr in v["frames"]:
                dets = []
                for tid, cls, conf, x1, y1, x2, y2 in fr:
                    d = Detection(box=(x1, y1, x2, y2), cls=cls, conf=conf, track_id=tid)
                    d.in_zone = self.zone.contains(d.foot_point, w, h)
                    dets.append(d)
                frames.append(dets)
            self._frames[video] = frames
        return self._frames[video]

    def breaches(self, video: str, conf: float, min_frames: int) -> list[tuple[int, str]]:
        """[(trigger_frame, 'person'), ...] that the live system would produce with these settings."""
        key = (video, conf, min_frames)
        if key not in self._memo:
            fps = self.cache[video]["fps"]
            trig, out = ZoneTrigger(fps, min_frames), []
            for i, dets in enumerate(self._detections(video)):
                fired = trig.update([d for d in dets if d.conf >= conf])
                if fired:
                    out.append((i, ", ".join(sorted({d.label for d in fired}))))
            self._memo[key] = out
        return self._memo[key]
