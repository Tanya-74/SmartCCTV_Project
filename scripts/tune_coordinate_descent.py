"""Tune the alert-decision parameters with Coordinate Descent (written by hand, no optimiser library).

    python scripts/tune_coordinate_descent.py

Needs only the caches made by build_tuning_cache.py - no videos, no YOLO, no Gemini calls.

THE IDEA IN ONE PARAGRAPH
Four settings decide whether the system raises an alert. We want values that give alerts on
incident videos and silence on normal ones. Coordinate Descent improves them ONE AT A TIME:
hold three settings fixed, try every allowed value of the fourth, keep the best, move on to the
next setting, and repeat the whole cycle until a full cycle changes nothing.

THE FOUR COORDINATES (the settings being tuned)
  alert_min_severity     only clips Gemini rates >= this become alerts
  yolo_conf              YOLO must be at least this sure that a box is a person/vehicle
  min_frames_in_zone     an object must stay in the zone this many frames in a row to count
  min_gemini_confidence  Gemini must be at least this sure of its own answer

THE OBJECTIVE  (we MAXIMISE it)
  J = F1  -  PENALTY * (number of alerts raised on normal videos)
  F1 is computed per VIDEO: "did the system raise at least one alert?" vs the file-name label.
  With only a handful of videos F1 jumps in big steps, so the penalty term (see --penalty) adds
  a smaller, graded cost for every false alarm. It is a modelling choice, not part of F1.
"""
from __future__ import annotations
import argparse
import itertools
import json
import time

import tuning_common as tc
from tuning_common import GRIDS, DEFAULTS

EPS = 1e-12


# ====================================================================== the objective function
class Objective:
    """Scores a parameter setting. Everything is looked up from the caches, so it is fast."""

    def __init__(self, det_cache: dict, gem_cache: dict, zone: str, penalty: float):
        self.gem, self.penalty = gem_cache, penalty
        self.replay = tc.Replay(det_cache, zone)
        self.cache = det_cache
        self.videos = [p.stem for p in tc.list_videos() if p.stem in det_cache]
        self.calls = 0                      # how many times the objective was evaluated
        self.missing = set()                # clips with no cached Gemini answer (should stay empty)

    def alerts_per_video(self, theta: dict) -> dict:
        counts = {}
        for v in self.videos:
            n, info = 0, self.cache[v]
            for idx, who in self.replay.breaches(v, theta["yolo_conf"], theta["min_frames_in_zone"]):
                key, _ = tc.clip_key(v, idx, who, info["fps"], info["n"])
                r = self.gem.get(key)
                if r is None:
                    self.missing.add(key)
                    continue
                if (r["event_type"] != "normal" and r["severity"] >= theta["alert_min_severity"]
                        and r["confidence"] >= theta["min_gemini_confidence"]):
                    n += 1
            counts[v] = n
        return counts

    def score(self, theta: dict) -> dict:
        """Full breakdown for one setting (used for reporting)."""
        alerts = self.alerts_per_video(theta)
        tp = fp = fn = tn = false_alarm_alerts = 0
        for v, n in alerts.items():
            truth, predicted = tc.label_of(v), n >= 1
            tp += truth == 1 and predicted
            fn += truth == 1 and not predicted
            fp += truth == 0 and predicted
            tn += truth == 0 and not predicted
            if truth == 0:
                false_alarm_alerts += n
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
        return {"alerts": alerts, "TP": tp, "FP": fp, "FN": fn, "TN": tn, "F1": f1,
                "false_alarm_alerts": false_alarm_alerts, "J": f1 - self.penalty * false_alarm_alerts}

    def __call__(self, theta: dict) -> float:
        self.calls += 1
        return self.score(theta)["J"]


# ====================================================================== coordinate descent
def coordinate_descent(objective, grids: dict, start: dict, max_cycles: int = 10):
    """Cycle through the coordinates; for each, a 1-D line search over its grid with the others fixed."""
    theta = dict(start)
    best = objective(theta)
    trace = [{"step": 0, "cycle": 0, "param": "start", "old": None, "new": None, "J": best, "changed": False}]
    line_searches = []                                   # kept for the report: J for every value tried
    converged = False
    for cycle in range(1, max_cycles + 1):
        changed_in_cycle = False
        for name in grids:                               # one coordinate at a time
            tried = [(v, objective({**theta, name: v})) for v in grids[name]]    # the 1-D line search
            top = max(score for _, score in tried)
            old = theta[name]
            changed = top > best + EPS                   # only move if STRICTLY better than where we are
            if changed:
                theta[name] = next(v for v, score in tried if score >= top - EPS)   # first best value
                best, changed_in_cycle = top, True
            trace.append({"step": len(trace), "cycle": cycle, "param": name, "old": old,
                          "new": theta[name], "J": best, "changed": changed})
            line_searches.append({"cycle": cycle, "param": name, "tried": tried})
        if not changed_in_cycle:                         # a whole cycle changed nothing -> converged
            converged = True
            break
    return theta, best, trace, line_searches, converged


# ====================================================================== grid search (for comparison)
def grid_search(objective, grids: dict):
    """Try EVERY combination. Slow in general (the grid multiplies) but certain within the grid."""
    names = list(grids)
    best, best_theta, ties = -1e9, None, 0
    for values in itertools.product(*(grids[n] for n in names)):
        theta = dict(zip(names, values))
        j = objective(theta)
        if j > best + EPS:
            best, best_theta, ties = j, theta, 1
        elif abs(j - best) <= EPS:
            ties += 1
    return best_theta, best, ties


# ====================================================================== reporting
def fmt(theta):
    return ", ".join(f"{k}={v}" for k, v in theta.items())


def make_plot(trace, grid_best, path, default_j):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(GRIDS)
    colors = dict(zip(names, ["#d62728", "#1f77b4", "#2ca02c", "#9467bd"]))
    short = {"alert_min_severity": "min severity", "yolo_conf": "YOLO conf",
             "min_frames_in_zone": "min frames", "min_gemini_confidence": "min Gemini conf"}
    xs, ys = [t["step"] for t in trace], [t["J"] for t in trace]

    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.step(xs, ys, where="post", color="#888", lw=1.4, zorder=1)
    ax.axhline(grid_best, color="black", ls="--", lw=1, label=f"grid-search best ({grid_best:.3f})")
    ax.axhline(default_j, color="#999", ls=":", lw=1, label=f"default settings ({default_j:.3f})")
    for t in trace[1:]:
        c = colors[t["param"]]
        if t["changed"]:
            ax.scatter(t["step"], t["J"], s=110, color=c, zorder=3, edgecolor="black")
            ax.annotate(f"{short[t['param']]}: {t['old']} -> {t['new']}", (t["step"], t["J"]),
                        textcoords="offset points", xytext=(6, 10), fontsize=8.5, color=c, rotation=20)
        else:
            ax.scatter(t["step"], t["J"], s=55, facecolor="white", edgecolor=c, lw=1.6, zorder=3)
    ax.scatter(0, trace[0]["J"], s=110, marker="s", color="black", zorder=4)
    for cyc in sorted({t["cycle"] for t in trace if t["cycle"] > 0}):
        first = next(t["step"] for t in trace if t["cycle"] == cyc)
        ax.axvline(first - 0.5, color="#ccc", lw=0.8)
        ax.text(first - 0.4, ax.get_ylim()[0], f" cycle {cyc}", fontsize=8, color="#666", va="bottom")
    handles = [plt.Line2D([], [], marker="o", ls="", color=colors[n], label=short[n]) for n in names]
    handles += [plt.Line2D([], [], marker="o", ls="", mfc="white", mec="#555", label="coordinate tried, no change"),
                plt.Line2D([], [], marker="o", ls="", mfc="#555", mec="black", ms=9, label="coordinate improved the objective")]
    ax.legend(handles=handles + ax.get_legend_handles_labels()[0][:2], fontsize=8, loc="lower right")
    ax.set_xlabel("iteration  (one iteration = one 1-D line search over one parameter)")
    ax.set_ylabel("objective  J = F1 - penalty x false alarms   (higher is better)")
    ax.set_title("Coordinate Descent on the alert parameters")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zone", choices=list(tc.ZONES), default="full", help="must match the cache builder")
    ap.add_argument("--penalty", type=float, default=0.05, help="J loses this much per alert on a normal video")
    ap.add_argument("--max-cycles", type=int, default=10)
    ap.add_argument("--plot", default=str(tc.ROOT / "tuning_coordinate_descent.png"))
    a = ap.parse_args()

    obj = Objective(tc.load_detections(), tc.load_gemini(), a.zone, a.penalty)
    print(f"videos: {len(obj.videos)}  "
          f"(incident={sum(tc.label_of(v) == 1 for v in obj.videos)}, normal={sum(tc.label_of(v) == 0 for v in obj.videos)})")
    print("grids:", {k: len(v) for k, v in GRIDS.items()},
          "-> grid-search size", len(list(itertools.product(*GRIDS.values()))), "\n")

    before = obj.score(DEFAULTS)

    t0 = time.time()
    obj.calls = 0
    cd_theta, cd_j, trace, lines, converged = coordinate_descent(obj, GRIDS, DEFAULTS, a.max_cycles)
    cd_calls, cd_time = obj.calls, time.time() - t0
    cycles = max(t["cycle"] for t in trace)

    t0 = time.time()
    obj.calls = 0
    gs_theta, gs_j, gs_ties = grid_search(obj, GRIDS)
    gs_calls, gs_time = obj.calls, time.time() - t0

    after = obj.score(cd_theta)
    gs_score = obj.score(gs_theta)

    print("COORDINATE DESCENT TRACE")
    for t in trace:
        if t["param"] == "start":
            print(f"  step  0  start at defaults                              J = {t['J']:.4f}")
        else:
            what = f"{t['old']} -> {t['new']}" if t["changed"] else f"stays {t['new']}"
            print(f"  step {t['step']:2d}  cycle {t['cycle']}  {t['param']:<22} {what:<14} J = {t['J']:.4f}")
    print(f"  {'converged' if converged else 'stopped at max cycles'} after {cycles} cycle(s)\n")

    rows = [("Parameter", "Default", "Tuned (CD)", "Grid-search best")]
    rows += [(k, DEFAULTS[k], cd_theta[k], gs_theta[k]) for k in GRIDS]
    rows += [("F1 (video level)", f"{before['F1']:.3f}", f"{after['F1']:.3f}", f"{gs_score['F1']:.3f}"),
             ("false-alarm alerts", before["false_alarm_alerts"], after["false_alarm_alerts"], gs_score["false_alarm_alerts"]),
             ("objective J", f"{before['J']:.3f}", f"{after['J']:.3f}", f"{gs_score['J']:.3f}"),
             ("TP / FP / FN / TN", "/".join(str(before[k]) for k in ("TP", "FP", "FN", "TN")),
              "/".join(str(after[k]) for k in ("TP", "FP", "FN", "TN")),
              "/".join(str(gs_score[k]) for k in ("TP", "FP", "FN", "TN")))]
    w = [max(len(str(r[i])) for r in rows) for i in range(4)]
    table = "\n".join("| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) + " |"
                      + ("\n|" + "|".join("-" * (w[i] + 2) for i in range(4)) + "|" if r is rows[0] else "")
                      for r in rows)

    vrows = [("Video", "Truth", "Alerts @ default", "Alerts @ tuned")]
    vrows += [(v, "incident" if tc.label_of(v) else "normal", before["alerts"][v], after["alerts"][v]) for v in obj.videos]
    vw = [max(len(str(r[i])) for r in vrows) for i in range(4)]
    vtable = "\n".join("| " + " | ".join(str(c).ljust(vw[i]) for i, c in enumerate(r)) + " |"
                       + ("\n|" + "|".join("-" * (vw[i] + 2) for i in range(4)) + "|" if r is vrows[0] else "")
                       for r in vrows)

    cost = (f"Coordinate Descent: {cd_calls} objective evaluations ({cycles} cycles x "
            f"{sum(len(g) for g in GRIDS.values())}), {cd_time:.2f}s, best J = {cd_j:.4f}\n"
            f"Grid search:        {gs_calls} objective evaluations, {gs_time:.2f}s, best J = {gs_j:.4f}; "
            f"{gs_ties} grid point(s) tie at that value")
    print(table + "\n\n" + vtable + "\n\n" + cost)
    if obj.missing:
        print(f"\nWARNING: {len(obj.missing)} breach(es) had no cached Gemini answer and were ignored. "
              "Re-run build_tuning_cache.py.")

    make_plot(trace, gs_j, a.plot, before["J"])
    print(f"\nplot saved -> {a.plot}")

    result = {"zone": a.zone, "penalty": a.penalty, "defaults": DEFAULTS, "tuned_cd": cd_theta,
              "grid_best": gs_theta, "before": before, "after_cd": after, "after_grid": gs_score,
              "cd": {"evaluations": cd_calls, "cycles": cycles, "converged": converged, "seconds": cd_time},
              "grid": {"evaluations": gs_calls, "ties_at_best": gs_ties, "seconds": gs_time},
              "trace": trace, "line_searches": lines}
    (tc.EXP_DIR / "tuning_results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    (tc.EXP_DIR / "tuning_results.md").write_text(
        f"### Parameters and scores\n\n{table}\n\n### Alerts per video\n\n{vtable}\n\n### Cost\n\n```\n{cost}\n```\n",
        encoding="utf-8")
    print(f"tables saved -> {tc.EXP_DIR / 'tuning_results.md'}")


if __name__ == "__main__":
    main()
