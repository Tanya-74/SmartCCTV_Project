"""Step 1 - Object detection (YOLOv8) + restricted-zone geometry.

Run standalone to test:
    python detection.py data/videos/Assault001_x264.mp4 --out data/detect_demo.mp4
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass

import cv2
import numpy as np
from ultralytics import YOLO

import config

LABELS = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@dataclass
class Detection:
    box: tuple          # x1, y1, x2, y2 in pixels
    cls: int
    conf: float
    track_id: int | None = None
    in_zone: bool = False

    @property
    def label(self) -> str:
        return LABELS.get(self.cls, str(self.cls))

    @property
    def foot_point(self) -> tuple:
        """Bottom-centre of the box: where the object touches the ground."""
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, y2)


class Zone:
    """A restricted-area polygon, stored normalised so it fits any resolution."""

    def __init__(self, points_norm=None):
        self.points_norm = list(points_norm or config.DEFAULT_ZONE)

    def pixels(self, w: int, h: int) -> np.ndarray:
        return np.array([(x * w, y * h) for x, y in self.points_norm], np.int32)

    def contains(self, pt, w: int, h: int) -> bool:
        return cv2.pointPolygonTest(self.pixels(w, h), (float(pt[0]), float(pt[1])), False) >= 0


class Detector:
    def __init__(self, weights: str = config.YOLO_WEIGHTS, device: str | None = None):
        self.model = YOLO(weights)
        self.device = device  # None -> ultralytics auto-picks the GPU if present

    def _parse(self, result, zone: Zone | None, w: int, h: int) -> list[Detection]:
        dets = []
        if result.boxes is None:
            return dets
        ids = result.boxes.id
        for i, b in enumerate(result.boxes):
            d = Detection(
                box=tuple(float(v) for v in b.xyxy[0].tolist()),
                cls=int(b.cls[0]),
                conf=float(b.conf[0]),
                track_id=int(ids[i]) if ids is not None else None,
            )
            if zone is not None:
                d.in_zone = zone.contains(d.foot_point, w, h)
            dets.append(d)
        return dets

    def detect(self, frame, zone: Zone | None = None) -> list[Detection]:
        """Plain per-frame detection (no tracking)."""
        h, w = frame.shape[:2]
        r = self.model.predict(frame, imgsz=config.YOLO_IMGSZ, conf=config.YOLO_CONF,
                               classes=config.TARGET_CLASSES, device=self.device, verbose=False)[0]
        return self._parse(r, zone, w, h)

    def track(self, frame, zone: Zone | None = None) -> list[Detection]:
        """Detection + ByteTrack IDs. Keeps tracker state between calls."""
        h, w = frame.shape[:2]
        r = self.model.track(frame, imgsz=config.YOLO_IMGSZ, conf=config.YOLO_CONF,
                             classes=config.TARGET_CLASSES, device=self.device,
                             tracker="bytetrack.yaml", persist=True, verbose=False)[0]
        return self._parse(r, zone, w, h)

    def reset_tracker(self):
        """Call between videos so IDs don't leak across files."""
        if getattr(self.model, "predictor", None) is not None:
            self.model.predictor = None


def draw(frame, dets: list[Detection], zone: Zone | None = None):
    h, w = frame.shape[:2]
    if zone is not None:
        poly = zone.pixels(w, h)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [poly], (0, 0, 255))
        frame = cv2.addWeighted(overlay, 0.18, frame, 0.82, 0)
        cv2.polylines(frame, [poly], True, (0, 0, 255), 2)
    for d in dets:
        x1, y1, x2, y2 = map(int, d.box)
        color = (0, 0, 255) if d.in_zone else (0, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tag = f"{'#'+str(d.track_id)+' ' if d.track_id is not None else ''}{d.label} {d.conf:.2f}"
        cv2.putText(frame, tag, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return frame


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="data/detect_demo.mp4")
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--snap", default="data/detect_snapshot.jpg")
    a = ap.parse_args()

    det, zone = Detector(), Zone()
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    n = in_zone_frames = total_dets = 0
    best = (-1, None)
    while n < a.max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        dets = det.detect(frame, zone)
        total_dets += len(dets)
        k = sum(d.in_zone for d in dets)
        in_zone_frames += k > 0
        vis = draw(frame.copy(), dets, zone)
        if len(dets) > best[0]:
            best = (len(dets), vis.copy())
        out.write(vis)
        n += 1
    out.release()
    if best[1] is not None:
        cv2.imwrite(a.snap, best[1])
    print(f"frames={n} detections={total_dets} avg/frame={total_dets/max(n,1):.2f} "
          f"frames_with_zone_breach={in_zone_frames}")
    print(f"annotated video -> {a.out}\nbusiest-frame snapshot -> {a.snap}")
