"""Step 3 - Vision-Language Model classification with Gemini.

Takes a few key frames from a buffered clip and returns structured JSON:
    {event_type, severity (1-5), description, confidence}
"""
from __future__ import annotations
import json
import time

import cv2
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Literal

import config


class Classification(BaseModel):
    event_type: Literal["normal", "intrusion", "theft", "assault", "robbery", "vandalism", "other"]
    severity: int = Field(ge=1, le=5)
    description: str
    confidence: float = Field(ge=0, le=1)


PROMPT = """You are a CCTV security analyst. The images are {n} frames, in time order, spanning \
about {secs:.0f} seconds of surveillance footage. A detector reports that {who} entered the \
restricted zone.

Classify what is happening. event_type must be one of: normal, intrusion, theft, assault, \
robbery, vandalism, other.
- normal: ordinary activity (people walking, authorised presence, false alarm from the detector).
- intrusion: someone is where they should not be, with no violence or taking of property.
- theft: property being taken without confrontation. robbery: property taken with force/threat.
- assault: physical violence against a person. vandalism: damage to property. other: anything else.
severity: 1 = harmless, 2 = minor/suspicious, 3 = serious, 4 = dangerous, 5 = critical/violent crime in progress.
Only describe what is visible; do not guess. The footage may be low resolution. \
description: 1-2 plain sentences. confidence: 0-1 for your classification."""


def sample_keyframes(frames: list, n: int = config.KEYFRAMES_PER_CLIP, max_side: int = 768) -> list:
    """Pick n evenly spaced frames (always including the first and last)."""
    if not frames:
        return []
    if len(frames) <= n:
        idx = list(range(len(frames)))
    else:
        idx = [round(i * (len(frames) - 1) / (n - 1)) for i in range(n)]
    out = []
    for i in idx:
        f = frames[i]
        h, w = f.shape[:2]
        s = max_side / max(h, w)
        if s > 1:  # upscale tiny CCTV frames a little so the model can see detail
            f = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
        out.append(f)
    return out


class VLMClassifier:
    def __init__(self):
        if not config.GEMINI_API_KEY or config.GEMINI_API_KEY.startswith("PASTE"):
            raise RuntimeError("GEMINI_API_KEY missing in .env")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY,
                                   http_options=types.HttpOptions(timeout=45000))  # 45 s per request
        self.models = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACKS if m != config.GEMINI_MODEL]

    def classify(self, frames: list, who: str = "a person", clip_seconds: float = config.BUFFER_SECONDS,
                 retries: int = 6) -> Classification:
        keyframes = sample_keyframes(frames)
        parts = [types.Part.from_bytes(data=cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes(),
                                       mime_type="image/jpeg") for f in keyframes]
        parts.append(PROMPT.format(n=len(keyframes), secs=clip_seconds, who=who))
        last = None
        for attempt in range(retries):
            # first try the primary model; on failure (overload/timeout) fall back to the next
            model = self.models[attempt % len(self.models)]
            try:
                r = self.client.models.generate_content(
                    model=model, contents=parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Classification,
                        temperature=0.2,
                    ))
                return Classification.model_validate_json(r.text)
            except Exception as e:  # rate limits / transient errors / bad JSON
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Gemini failed after {retries} tries: {last}")


if __name__ == "__main__":
    # Quick test: run on a video, classify the first breach clip.
    import sys
    from detection import Detector, Zone
    from tracking import ZoneMonitor

    path = sys.argv[1]
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    mon = ZoneMonitor(Detector(), Zone(), fps)
    clf = VLMClassifier()
    count = 0
    while count < 2:
        ok, frame = cap.read()
        if not ok:
            break
        _, breach = mon.process(frame)
        if breach:
            count += 1
            res = clf.classify(breach.frames, who=", ".join(breach.labels), clip_seconds=len(breach.frames) / fps)
            print(f"t={breach.timestamp_sec:.1f}s -> {res.model_dump_json(indent=1)}")
    tail = mon.flush()
    if tail:
        print("(a final breach near the end of the video was also detected)")
