"""Build the two caches the tuning experiment needs. Run ONCE (needs the videos + Gemini key).

    python scripts/build_tuning_cache.py            # detections, then Gemini clip bank
    python scripts/build_tuning_cache.py --dry-run  # only report how many Gemini calls are needed

Step A - detections: run YOLOv8 + ByteTrack once per video at a very low confidence (0.15) and
         save every box. Stricter confidences are simulated later by dropping weak boxes.
Step B - clip bank: work out every breach that ANY parameter setting could trigger, and send each
         distinct clip to Gemini exactly once. Answers are saved after each call, so the script
         can be stopped and restarted without repeating work.
"""
from __future__ import annotations
import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2

import tuning_common as tc
import config


def build_detections(redo: bool):
    from detection import Detector
    cache = {} if (redo or not tc.DET_CACHE.exists()) else tc.load_detections()
    det = Detector()
    config.YOLO_CONF = tc.LOW_CONF            # detect loosely; the tuner filters upwards later
    for path in tc.list_videos():
        name = path.stem
        if name in cache:
            print(f"[detections] {name}: already cached")
            continue
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        w, h = int(cap.get(3)), int(cap.get(4))
        det.reset_tracker()
        frames, t0 = [], time.time()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append([[d.track_id, d.cls, round(d.conf, 3), *[round(v, 1) for v in d.box]]
                           for d in det.track(frame) if d.track_id is not None])
        cap.release()
        cache[name] = {"fps": fps, "w": w, "h": h, "n": len(frames), "frames": frames}
        print(f"[detections] {name}: {len(frames)} frames in {time.time() - t0:.0f}s", flush=True)
        tc.save_detections(cache)             # save after every video
    cache["_meta"] = {"yolo_weights": config.YOLO_WEIGHTS, "imgsz": config.YOLO_IMGSZ, "low_conf": tc.LOW_CONF}
    tc.save_detections(cache)
    return cache


def needed_clips(det_cache: dict, zone_name: str) -> dict:
    """Every distinct clip any grid combination could ask Gemini about: key -> (video, q_frame, who)."""
    replay = tc.Replay(det_cache, zone_name)
    need = {}
    for path in tc.list_videos():
        v = path.stem
        if v not in det_cache:
            continue
        info = det_cache[v]
        for conf in tc.GRIDS["yolo_conf"]:
            for mf in tc.GRIDS["min_frames_in_zone"]:
                for idx, who in replay.breaches(v, conf, mf):
                    key, q = tc.clip_key(v, idx, who, info["fps"], info["n"])
                    need[key] = (v, q, who)
    return need


def read_clip(video: str, q: int, fps: float, n: int):
    start, end = tc.clip_range(q, fps, n)
    cap = cv2.VideoCapture(str(tc.VIDEO_DIR / f"{video}.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames = []
    for _ in range(end - start + 1):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", choices=list(tc.ZONES), default="full",
                    help="zone used while building the clip bank (the tuner must use the same one)")
    ap.add_argument("--workers", type=int, default=3, help="parallel Gemini calls")
    ap.add_argument("--redo-detections", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    det_cache = build_detections(a.redo_detections) if not a.dry_run or not tc.DET_CACHE.exists() else tc.load_detections()
    gem = tc.load_gemini()
    need = needed_clips(det_cache, a.zone)
    todo = {k: v for k, v in need.items() if k not in gem}
    print(f"\nclips any setting could trigger: {len(need)} | already cached: {len(need) - len(todo)} "
          f"| Gemini calls needed now: {len(todo)}")
    for p in tc.list_videos():
        print(f"   {p.stem}: {sum(1 for k in need if k.startswith(p.stem + '|'))} clips")
    if a.dry_run or not todo:
        return

    from vlm import VLMClassifier
    clf, lock, done = VLMClassifier(), threading.Lock(), [0]

    def work(key, v, q, who):
        info = det_cache[v]
        frames = read_clip(v, q, info["fps"], info["n"])
        res = clf.classify(frames, who=who, clip_seconds=len(frames) / info["fps"])
        return key, {"event_type": res.event_type, "severity": res.severity,
                     "confidence": res.confidence, "description": res.description}

    t0, failed = time.time(), []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(work, k, *v): k for k, v in todo.items()}
        for fut in as_completed(futs):
            try:
                key, rec = fut.result()
                with lock:
                    gem[key] = rec
                    tc.save_gemini(gem)
            except Exception as e:
                failed.append(futs[fut])
                print(f"   FAILED {futs[fut]}: {str(e)[:100]}", flush=True)
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(todo):
                print(f"   {done[0]}/{len(todo)} done ({time.time() - t0:.0f}s)", flush=True)
    print(f"\nGemini cache now holds {len(gem)} clips. Failed this run: {len(failed)}"
          + (" - just run the script again to retry them." if failed else ""))


if __name__ == "__main__":
    main()
