"""Central settings for the Smart CCTV project."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
ALERT_DIR = DATA_DIR / "alerts"
VIDEO_DIR = DATA_DIR / "videos"
for _d in (UPLOAD_DIR, ALERT_DIR, VIDEO_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Detection ---
YOLO_WEIGHTS = os.getenv("YOLO_WEIGHTS", "yolov8s.pt")
YOLO_IMGSZ = 640
YOLO_CONF = 0.35
# COCO class ids: person, bicycle, car, motorcycle, bus, truck
TARGET_CLASSES = [0, 1, 2, 3, 5, 7]

# Restricted zone as a polygon in NORMALISED coordinates (0-1, x then y) so it
# works for any video resolution. Default: lower-centre block of the frame.
DEFAULT_ZONE = [(0.25, 0.45), (0.75, 0.45), (0.85, 0.95), (0.15, 0.95)]

# --- Trigger / clip buffer ---
BUFFER_SECONDS = 4          # video kept BEFORE the breach
KEYFRAMES_PER_CLIP = 6      # frames sent to the VLM
POST_TRIGGER_SECONDS = 2     # extra footage kept AFTER the trigger
REANALYSE_SECONDS = 15       # someone still in the zone is re-checked this often
BREACH_COOLDOWN_SEC = 10    # min gap between two triggers for the same video

# --- VLM ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACKS = ["gemini-3.1-flash-lite", "gemini-3.8-flash"]  # tried in order if primary fails
EVENT_TYPES = ["normal", "intrusion", "theft", "assault", "robbery", "vandalism", "other"]

# --- Alerts ---
ALERT_MIN_SEVERITY = 3
