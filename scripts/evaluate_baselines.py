"""Baselines, dataset statistics and charts for the final report. Fully OFFLINE (uses the caches).

    python scripts/evaluate_baselines.py

Writes report/results.json and report/*.png. Same 6 videos, same video-level F1 as the tuning experiment.
"""
from __future__ import annotations
import collections
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
import tuning_common as tc
from tune_coordinate_descent import Objective

OUT = tc.ROOT / "report"
OUT.mkdir(exist_ok=True)


def f1_of(truth_pred):
    tp = sum(t == 1 and p for t, p in truth_pred)
    fp = sum(t == 0 and p for t, p in truth_pred)
    fn = sum(t == 1 and not p for t, p in truth_pred)
    tn = sum(t == 0 and not p for t, p in truth_pred)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
    return dict(TP=tp, FP=fp, FN=fn, TN=tn, precision=round(prec, 3), recall=round(rec, 3), F1=round(f1, 3))


def main():
    det, gem = tc.load_detections(), tc.load_gemini()
    obj = Objective(det, gem, "full", 0.05)
    D = tc.DEFAULTS
    videos = obj.videos
    truth = {v: tc.label_of(v) for v in videos}

    # ---- dataset table + breaches (zone = whole frame, default thresholds)
    rows, breach_n = [], {}
    for v in videos:
        info = det[v]
        b = obj.replay.breaches(v, D["yolo_conf"], D["min_frames_in_zone"])
        breach_n[v] = len(b)
        cls = collections.Counter()
        for fr in info["frames"]:
            for d in fr:
                if d[2] >= D["yolo_conf"]:
                    cls[d[1]] += 1
        rows.append(dict(video=v, label="incident" if truth[v] else "normal", frames=info["n"],
                         fps=round(info["fps"], 1), width=info["w"], height=info["h"],
                         seconds=round(info["n"] / info["fps"], 1), breaches=len(b),
                         boxes_person=cls[0], boxes_vehicle=sum(cls[c] for c in (1, 2, 3, 5, 7))))

    # ---- baselines (video level)
    base = {}
    base["B0 never alert"] = f1_of([(truth[v], False) for v in videos])
    base["B1 always alert (majority class)"] = f1_of([(truth[v], True) for v in videos])
    base["B2 zone breach only (no VLM)"] = f1_of([(truth[v], breach_n[v] > 0) for v in videos])
    s = obj.score(D)
    base["Ours: YOLO+track+zone+Gemini (defaults)"] = f1_of([(truth[v], s["alerts"][v] > 0) for v in videos])
    tuned = dict(D, alert_min_severity=1)
    s2 = obj.score(tuned)
    base["Ours, severity>=1 (tuning result, NOT adopted)"] = f1_of([(truth[v], s2["alerts"][v] > 0) for v in videos])
    alerts_default, alerts_tuned = s["alerts"], s2["alerts"]

    # ---- ablation: alert threshold
    abl = []
    for sev in (1, 2, 3, 4, 5):
        sc = obj.score(dict(D, alert_min_severity=sev))
        abl.append(dict(sev=sev, F1=round(sc["F1"], 3), FP=sc["FP"], FN=sc["FN"],
                        false_alarm_alerts=sc["false_alarm_alerts"]))
    abl_conf = []
    for c in (0.0, 0.8, 0.9, 0.95):
        sc = obj.score(dict(D, min_gemini_confidence=c))
        abl_conf.append(dict(min_conf=c, F1=round(sc["F1"], 3), FP=sc["FP"], FN=sc["FN"]))

    # ---- Gemini outputs used by the default breaches (clip level)
    keys = []
    for v in videos:
        for idx, who in obj.replay.breaches(v, D["yolo_conf"], D["min_frames_in_zone"]):
            k, _ = tc.clip_key(v, idx, who, det[v]["fps"], det[v]["n"])
            if k in gem:
                keys.append((v, gem[k]))
    ev = collections.Counter(r["event_type"] for _, r in keys)
    sev = collections.Counter(r["severity"] for _, r in keys)
    conf = [r["confidence"] for _, r in keys]
    per_video_events = {v: dict(collections.Counter(r["event_type"] for vv, r in keys if vv == v)) for v in videos}

    results = dict(videos=rows, baselines=base, severity_ablation=abl, confidence_ablation=abl_conf,
                   event_types=dict(ev), severities={str(k): v for k, v in sorted(sev.items())},
                   gemini_conf_min=min(conf), gemini_conf_max=max(conf), clips_scored=len(keys),
                   alerts_default=alerts_default, alerts_sev1=alerts_tuned, per_video_events=per_video_events)
    (OUT / "results.json").write_text(json.dumps(results, indent=1))

    # ---- charts
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    short = [v.split("_x264")[0].replace("_Videos_003", "").replace("shanghaitech_01_0014", "ShanghaiTech") for v in videos]
    colors = ["#c0392b" if truth[v] else "#2e86c1" for v in videos]

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].bar(short, [breach_n[v] for v in videos], color=colors)
    ax[0].set_title("Zone breaches found per video"); ax[0].set_ylabel("breach events")
    plt.setp(ax[0].get_xticklabels(), rotation=30, ha="right")
    ax[1].bar(short, [alerts_default[v] for v in videos], color=colors)
    ax[1].set_title("Alerts raised (severity >= 3)"); ax[1].set_ylabel("alerts")
    plt.setp(ax[1].get_xticklabels(), rotation=30, ha="right")
    fig.text(0.5, 0.0, "red = incident video, blue = normal video", ha="center", fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / "eda_breaches_alerts.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ev_items = sorted(ev.items(), key=lambda kv: -kv[1])
    ax[0].barh([k for k, _ in ev_items][::-1], [n for _, n in ev_items][::-1], color="#5d6d7e")
    ax[0].set_title("Gemini event types (all breach clips)"); ax[0].set_xlabel("clips")
    ax[1].bar([str(k) for k in range(1, 6)], [sev.get(k, 0) for k in range(1, 6)],
              color=["#7fb3d5", "#7fb3d5", "#f5b041", "#e67e22", "#c0392b"])
    ax[1].set_title("Gemini severity (1-5)"); ax[1].set_xlabel("severity"); ax[1].set_ylabel("clips")
    ax[1].axvline(1.5 + 1, color="k", ls="--", lw=1); ax[1].text(3.55, ax[1].get_ylim()[1] * 0.97, "alert if >= 3", fontsize=9, va="top")
    fig.tight_layout(); fig.savefig(OUT / "eda_gemini_outputs.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    names = list(base)
    ax.barh([n.replace(" (", "\n(") for n in names][::-1], [base[n]["F1"] for n in names][::-1],
            color=["#c0392b" if n.startswith("Ours, sev") else "#1e8449" if n.startswith("Ours") else "#85929e"
                   for n in names][::-1])
    ax.set_xlim(0, 1.05); ax.set_xlabel("video-level F1 (6 videos)"); ax.set_title("Comparison with baselines")
    for i, n in enumerate(names[::-1]):
        ax.text(base[n]["F1"] + 0.01, i, f'{base[n]["F1"]:.2f}', va="center")
    fig.tight_layout(); fig.savefig(OUT / "baseline_comparison.png", dpi=160); plt.close(fig)

    print(json.dumps(base, indent=1)); print(json.dumps(abl)); print(dict(ev), dict(sev), min(conf), max(conf))
    print(json.dumps(rows, indent=0)[:1500])


if __name__ == "__main__":
    main()
