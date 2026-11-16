"""Step 2 - Tracking (ByteTrack) + zone-breach trigger + rolling clip buffer.

ZoneMonitor consumes frames one at a time. It keeps the last N seconds of
frames in memory; when a tracked object FIRST enters the restricted zone it
emits a Breach containing that buffered clip.

Run standalone:
    python tracking.py data/videos/Assault001_x264.mp4
"""
from __future__ import annotations
import argparse
from collections import deque
from dataclasses import dataclass, field

import cv2

import config
from detection import Detector, Zone, Detection, draw


@dataclass
class Breach:
    frame_index: int
    timestamp_sec: float
    track_ids: list
    labels: list
    frames: list = field(repr=False)        # buffered BGR frames (annotated=False)
    annotated_frame: object = field(default=None, repr=False)  # snapshot at trigger moment


class ZoneMonitor:
    def __init__(self, detector: Detector, zone: Zone, fps: float,
                 buffer_seconds: float = config.BUFFER_SECONDS,
                 cooldown_sec: float = config.BREACH_COOLDOWN_SEC,
                 min_frames_in_zone: int = 3,
                 post_seconds: float = config.POST_TRIGGER_SECONDS):
        self.det, self.zone, self.fps = detector, zone, fps or 30.0
        self.buffer = deque(maxlen=max(1, int(self.fps * buffer_seconds)))
        self.cooldown_frames = int(self.fps * cooldown_sec)
        self.min_frames = min_frames_in_zone
        self.post_frames = int(self.fps * post_seconds)
        self.pending: Breach | None = None   # breach waiting for its post-trigger frames
        self.pending_left = 0
        self.in_zone_count: dict[int, int] = {}   # track id -> consecutive frames inside
        self.flagged_at: dict[int, int] = {}      # id -> frame index when it last caused a breach
        self.reflag_frames = int(self.fps * config.REANALYSE_SECONDS)
        self.last_trigger = -10**9
        self.idx = 0
        self.det.reset_tracker()

    def flush(self):
        """Call at end of video: emit a breach still waiting for post-trigger frames."""
        b, self.pending = self.pending, None
        return b

    def process(self, frame):
        """Returns (detections, Breach|None) for this frame."""
        dets = self.det.track(frame, self.zone)
        self.buffer.append(frame.copy())

        visible = set()
        newly = []
        for d in dets:
            if d.track_id is None:
                continue
            visible.add(d.track_id)
            if d.in_zone:
                c = self.in_zone_count.get(d.track_id, 0) + 1
                self.in_zone_count[d.track_id] = c
                # require a few consecutive frames to ignore flicker / box jitter
                last = self.flagged_at.get(d.track_id)
                if c >= self.min_frames and (last is None or self.idx - last >= self.reflag_frames):
                    newly.append(d)
            else:
                self.in_zone_count[d.track_id] = 0
        for tid in list(self.in_zone_count):
            if tid not in visible:
                self.in_zone_count.pop(tid)

        # A breach is created at the trigger moment, then keeps collecting
        # `post_frames` more frames so the clip shows what happens AFTER entry too.
        breach = None
        if self.pending is not None:
            self.pending.frames.append(frame.copy())
            self.pending_left -= 1
            if self.pending_left <= 0:
                breach, self.pending = self.pending, None
        if newly and self.pending is None and breach is None and (self.idx - self.last_trigger) >= self.cooldown_frames:
            self.last_trigger = self.idx
            self.flagged_at.update({d.track_id: self.idx for d in newly})
            self.pending = Breach(
                frame_index=self.idx,
                timestamp_sec=self.idx / self.fps,
                track_ids=[d.track_id for d in newly],
                labels=[d.label for d in newly],
                frames=list(self.buffer),
                annotated_frame=draw(frame.copy(), dets, self.zone),
            )
            self.pending_left = self.post_frames
            if self.pending_left <= 0:
                breach, self.pending = self.pending, None
        self.idx += 1
        return dets, breach


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="data/track_demo.mp4")
    ap.add_argument("--max-frames", type=int, default=900)
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w, h = int(cap.get(3)), int(cap.get(4))
    out = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    mon = ZoneMonitor(Detector(), Zone(), fps)
    n, banner_until, ids_seen = 0, -1, set()
    while n < a.max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        dets, breach = mon.process(frame)
        ids_seen.update(d.track_id for d in dets if d.track_id is not None)
        vis = draw(frame.copy(), dets, mon.zone)
        if breach:
            banner_until = n + int(fps * 2)
            print(f"BREACH at {breach.timestamp_sec:5.1f}s (frame {breach.frame_index}) "
                  f"ids={breach.track_ids} {breach.labels} clip_frames={len(breach.frames)}")
            cv2.imwrite(f"data/breach_{breach.frame_index}.jpg", breach.annotated_frame)
        if n < banner_until:
            cv2.putText(vis, "ZONE BREACH", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        out.write(vis)
        n += 1
    out.release()
    print(f"frames={n} unique_tracks={len(ids_seen)} -> {a.out}")
