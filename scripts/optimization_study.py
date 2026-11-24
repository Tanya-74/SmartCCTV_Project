"""CS4101 optimisation study: choose the alert-decision parameters of the Smart CCTV system. FULLY OFFLINE.

    python scripts/optimization_study.py            # ~1-3 minutes, writes optimization/*.png and results.json

Problem (see the report, Section 2):  maximise J(x) = F1(x) - lambda * FA(x)   over a box-bounded discrete set
x = (alert_min_severity, yolo_conf, min_frames_in_zone, min_gemini_confidence).
J is evaluated by replaying cached YOLO detections + cached Gemini answers (see tuning_common.py), so one
objective evaluation costs about a millisecond and no network is needed.

Algorithms (all on the SAME objective):
  CD    Coordinate Descent (hand-written, in tune_coordinate_descent.py)
  SA    Simulated Annealing (hand-written below)
  RS    Random Search (baseline, same budget as SA)
  NM    Nelder-Mead (hand-written) on a rounded continuous relaxation; NM-wide uses a wide start simplex
  GS    Grid Search (exhaustive reference, gives the true optimum on the grid)
Extension: HYB = SA for a short budget, then Coordinate Descent from SA's best point.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import tuning_common as tc
from tuning_common import GRIDS, DEFAULTS
from tune_coordinate_descent import Objective, coordinate_descent, grid_search

OUT = tc.ROOT / "optimization"
OUT.mkdir(exist_ok=True)
NAMES = list(GRIDS)
SIZES = [len(GRIDS[n]) for n in NAMES]
PENALTY = 0.05
EPS = 1e-9
N_STARTS = 100                 # random initial points per algorithm
BUDGET = 300                   # evaluations for SA / RS / NM
HYB_SA_BUDGET = 120            # evaluations spent on SA inside the hybrid before the CD polish


def to_theta(z):
    return {n: GRIDS[n][int(i)] for n, i in zip(NAMES, z)}


class Tracker:
    """Wraps the objective: counts evaluations and records J after every call (for convergence plots)."""

    def __init__(self, obj):
        self.obj, self.log = obj, []

    def __call__(self, theta):
        j = self.obj.score(theta)["J"]
        self.log.append(j)
        return j

    def best_so_far(self):
        return np.maximum.accumulate(np.array(self.log))


# ------------------------------------------------------------------------------ simulated annealing
def simulated_annealing(f, z0, budget, rng, t0=0.2, t_end=0.005):
    """Metropolis rule on the integer grid. Move: change ONE coordinate by 1 or 2 grid steps.
    Accept if J does not drop, else with probability exp(dJ / T). Geometric cooling T_k = t0 * a**k."""
    z = np.array(z0); cur = f(to_theta(z)); best_z, best = z.copy(), cur
    alpha = (t_end / t0) ** (1.0 / max(budget - 1, 1)); T = t0
    for _ in range(budget - 1):
        c = rng.integers(len(z)); step = rng.choice([-2, -1, 1, 2])
        z2 = z.copy(); z2[c] = int(np.clip(z2[c] + step, 0, SIZES[c] - 1))
        if z2[c] != z[c]:
            j2 = f(to_theta(z2))
            if j2 >= cur or rng.random() < np.exp((j2 - cur) / T):
                z, cur = z2, j2
                if cur > best + EPS:
                    best_z, best = z.copy(), cur
        else:
            f.log.append(cur) if isinstance(f, Tracker) else None   # clipped move: counts as a (free) wasted step
        T *= alpha
    return best_z, best


def random_search(f, budget, rng):
    best = -1e9
    for _ in range(budget):
        z = [rng.integers(s) for s in SIZES]
        best = max(best, f(to_theta(z)))
    return best


def nelder_mead(f, z0, budget, wide=False):
    """Nelder-Mead simplex on the continuous relaxation x in R^4 (J is evaluated at the rounded, clipped point).
    Reflection a=1, expansion g=2, contraction r=0.5, shrink s=0.5. Stops after `budget` evaluations or when the
    simplex values are all equal (flat plateau) / the simplex has collapsed."""
    hi = np.array(SIZES) - 1.0
    fun = lambda x: -f(to_theta(np.clip(np.rint(x), 0, hi)))
    z0 = np.array(z0, float); n = len(z0)
    h = 2.5 if wide else 0.05 * max(1.0, 1.0)          # default simplex edge is tiny (5%) -> rounds to the same grid point
    simplex = [z0] + [z0 + h * np.eye(n)[i] for i in range(n)]
    vals = [fun(x) for x in simplex]; used = len(vals)
    while used < budget:
        order = np.argsort(vals); simplex = [simplex[i] for i in order]; vals = [vals[i] for i in order]
        if max(vals) - min(vals) < 1e-12 or max(np.abs(simplex[-1] - simplex[0])) < 1e-3:
            break
        c = np.mean(simplex[:-1], axis=0); xr = c + (c - simplex[-1]); fr = fun(xr); used += 1
        if fr < vals[0]:
            xe = c + 2 * (c - simplex[-1]); fe = fun(xe); used += 1
            simplex[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = xr, fr
        else:
            xc = c + 0.5 * ((xr if fr < vals[-1] else simplex[-1]) - c); fc = fun(xc); used += 1
            if fc < min(fr, vals[-1]):
                simplex[-1], vals[-1] = xc, fc
            else:
                simplex = [simplex[0]] + [simplex[0] + 0.5 * (x - simplex[0]) for x in simplex[1:]]
                vals = [vals[0]] + [fun(x) for x in simplex[1:]]; used += n
    return -min(vals)


def run_method(name, obj, z0, rng):
    """Run one algorithm from index-start z0; returns (best J, tracker)."""
    f = Tracker(obj)
    if name == "CD":
        _, best, *_ = coordinate_descent(f, GRIDS, to_theta(z0), max_cycles=10)
    elif name == "SA":
        _, best = simulated_annealing(f, z0, BUDGET, rng)
    elif name == "RS":
        best = random_search(f, BUDGET, rng)
    elif name == "NM":
        best = nelder_mead(f, z0, BUDGET)
    elif name == "NM-wide":
        best = nelder_mead(f, z0, BUDGET, wide=True)
    elif name == "HYB":
        zb, _ = simulated_annealing(f, z0, HYB_SA_BUDGET, rng)
        _, best, *_ = coordinate_descent(f, GRIDS, to_theta(zb), max_cycles=10)
    return max(f.log), f


def main():
    det, gem = tc.load_detections(), tc.load_gemini()
    obj = Objective(det, gem, "full", PENALTY)
    default_z = [GRIDS[n].index(DEFAULTS[n]) for n in NAMES]

    # ---- reference optimum by exhaustive search
    t = time.time(); gs_theta, gs_best, ties = grid_search(obj, GRIDS); gs_time = time.time() - t
    n_grid = int(np.prod(SIZES)); J_STAR = gs_best
    J_default = obj.score(DEFAULTS)["J"]
    print(f"grid: {n_grid} points, best J={gs_best:.4f}, {ties} ties, default J={J_default:.4f}")

    methods = ["CD", "SA", "RS", "NM", "NM-wide", "HYB"]

    # ---- 1. single run from the DEFAULT point (seed 0) -> convergence plot
    single = {}
    for m in methods:
        t = time.time(); b, f = run_method(m, obj, default_z, np.random.default_rng(0)); dt = time.time() - t
        single[m] = dict(best=b, evals=len(f.log), time_ms=1000 * dt, curve=f.best_so_far().tolist(),
                         first_hit=next((i + 1 for i, v in enumerate(f.best_so_far()) if v >= J_STAR - EPS), None))
    single["GS"] = dict(best=gs_best, evals=n_grid, time_ms=1000 * gs_time, first_hit=None)

    # ---- 2. effect of the initial point: N_STARTS random starts per method
    multi = {m: dict(best=[], evals=[], time=[], hit=[]) for m in methods}
    curves = {m: [] for m in methods}
    for seed in range(N_STARTS):
        rng0 = np.random.default_rng(1000 + seed)
        z0 = [rng0.integers(s) for s in SIZES]
        for m in methods:
            t = time.time(); b, f = run_method(m, obj, z0, np.random.default_rng(seed)); dt = time.time() - t
            multi[m]["best"].append(b); multi[m]["evals"].append(len(f.log)); multi[m]["time"].append(1000 * dt)
            multi[m]["hit"].append(next((i + 1 for i, v in enumerate(f.best_so_far()) if v >= J_STAR - EPS), None))
            cv = f.best_so_far(); curves[m].append(np.pad(cv, (0, BUDGET + 40 - len(cv)), mode="edge")[:BUDGET + 40])
    summary = {}
    for m in methods:
        b = np.array(multi[m]["best"]); hits = [h for h in multi[m]["hit"] if h is not None]
        summary[m] = dict(success_rate=float(np.mean(b >= J_STAR - EPS)), mean_J=float(b.mean()), min_J=float(b.min()),
                          mean_evals=float(np.mean(multi[m]["evals"])), mean_evals_to_opt=float(np.mean(hits)) if hits else None,
                          median_evals_to_opt=float(np.median(hits)) if hits else None, mean_time_ms=float(np.mean(multi[m]["time"])))
        print(m, {k: (round(v, 3) if v is not None else None) for k, v in summary[m].items()})

    # ---- 3a. effect of SA parameters (initial temperature, budget) - success rate over 100 seeds
    sa_grid = {}
    for t0 in (0.01, 0.05, 0.2, 0.5):
        for bud in (50, 150, 300):
            ok = 0
            for seed in range(N_STARTS):
                rng0 = np.random.default_rng(1000 + seed); z0 = [rng0.integers(s) for s in SIZES]
                f = Tracker(obj); _, b = simulated_annealing(f, z0, bud, np.random.default_rng(seed), t0=t0)
                ok += b >= J_STAR - EPS
            sa_grid[f"T0={t0}|budget={bud}"] = ok / N_STARTS

    # ---- 3b. effect of the CD coordinate ORDER (all 24 permutations, start = default)
    import itertools
    orders = {}
    for perm in itertools.permutations(range(4)):
        g = {NAMES[i]: GRIDS[NAMES[i]] for i in perm}
        f = Tracker(obj); th, b, *_ = coordinate_descent(f, g, DEFAULTS, max_cycles=10)
        orders["->".join(NAMES[i].split("_")[0] if i != 3 else "gconf" for i in perm)] = dict(J=b, evals=len(f.log))
    order_J = [v["J"] for v in orders.values()]

    # ---- 3c. effect of the false-alarm penalty lambda on the grid optimum and on the CD result
    lam_rows = []
    for lam in (0.0, 0.05, 0.2, 0.5):
        o2 = Objective(det, gem, "full", lam)
        th_g, bj, ties2 = grid_search(o2, GRIDS)
        th_c, cj, *_ = coordinate_descent(o2, GRIDS, DEFAULTS, 10)
        lam_rows.append(dict(lam=lam, grid_best=bj, grid_ties=ties2, cd_best=cj, cd_theta=th_c))

    # ---- figures
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    col = {"CD": "#c0392b", "SA": "#2e86c1", "RS": "#7f8c8d", "NM": "#af7ac5", "NM-wide": "#8e44ad", "HYB": "#1e8449"}

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    for m in methods:
        c = single[m]["curve"]; ax.step(range(1, len(c) + 1), c, where="post", color=col[m], lw=2, label=f"{m} ({single[m]['evals']} evals)")
    ax.axhline(J_STAR, color="k", ls="--", lw=1, label=f"grid-search optimum J*={J_STAR:.2f}")
    ax.axhline(J_default, color="#aaa", ls=":", lw=1, label=f"default point J={J_default:.3f}")
    ax.set_xscale("log"); ax.set_xlabel("objective evaluations (log scale)"); ax.set_ylabel("best J found so far")
    ax.set_title("Convergence from the default starting point"); ax.legend(fontsize=8.5, loc="lower right"); ax.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "convergence_single.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    for m in methods:
        arr = np.array(curves[m]); mu = arr.mean(0); x = np.arange(1, arr.shape[1] + 1)
        ax.plot(x, mu, color=col[m], lw=2, label=m); ax.fill_between(x, arr.min(0), arr.max(0), color=col[m], alpha=.08)
    ax.axhline(J_STAR, color="k", ls="--", lw=1)
    ax.set_xscale("log"); ax.set_xlabel("objective evaluations (log scale)"); ax.set_ylabel("best J so far (mean over 100 random starts)")
    ax.set_title("Convergence averaged over 100 random initial points (band = min..max)"); ax.legend(fontsize=9, loc="lower right"); ax.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "convergence_multistart.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(10.4, 4))
    ax[0].bar(methods, [100 * summary[m]["success_rate"] for m in methods], color=[col[m] for m in methods])
    ax[0].set_ylabel("% of 100 random starts reaching J*"); ax[0].set_title("Success rate"); ax[0].set_ylim(0, 105)
    for i, m in enumerate(methods): ax[0].text(i, 100 * summary[m]["success_rate"] + 2, f'{100 * summary[m]["success_rate"]:.0f}%', ha="center", fontsize=9)
    ev = [summary[m]["median_evals_to_opt"] or 0 for m in methods]
    ax[1].bar(methods, ev, color=[col[m] for m in methods]); ax[1].set_yscale("log")
    ax[1].set_ylabel("median evaluations until J* first reached"); ax[1].set_title("Cost to reach the optimum")
    for i, v in enumerate(ev): ax[1].text(i, max(v, 1) * 1.1, f"{v:.0f}" if v else "never", ha="center", fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / "initial_point_effect.png", dpi=160); plt.close(fig)

    # landscape slices through the CD solution
    th_c, _, *_ = coordinate_descent(Tracker(obj), GRIDS, DEFAULTS, 10)
    fig, ax = plt.subplots(1, 4, figsize=(13, 3.4), sharey=True)
    for k, n in enumerate(NAMES):
        ys = [obj.score({**th_c, n: v})["J"] for v in GRIDS[n]]
        ax[k].plot(range(len(ys)), ys, "o-", color="#2e4053"); ax[k].set_xticks(range(len(ys)))
        ax[k].set_xticklabels([str(v) for v in GRIDS[n]], rotation=60, fontsize=8); ax[k].set_title(n.replace("_", " "), fontsize=9)
        ax[k].axvline(GRIDS[n].index(th_c[n]), color="#c0392b", ls=":", lw=1); ax[k].grid(alpha=.25)
    ax[0].set_ylabel("J (other 3 parameters fixed at CD solution)")
    fig.tight_layout(); fig.savefig(OUT / "landscape_slices.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.hist(order_J, bins=np.linspace(min(order_J) - .01, max(order_J) + .01, 12), color="#2e86c1")
    ax.set_xlabel("final J of Coordinate Descent"); ax.set_ylabel("number of coordinate orders (of 24)")
    ax.set_title("Effect of coordinate order (start = default)")
    fig.tight_layout(); fig.savefig(OUT / "cd_order_effect.png", dpi=160); plt.close(fig)

    res = dict(n_grid=n_grid, J_star=J_STAR, grid_ties=ties, grid_theta=gs_theta, J_default=J_default, penalty=PENALTY,
               n_starts=N_STARTS, budget=BUDGET, hyb_sa_budget=HYB_SA_BUDGET, single={k: {a: b for a, b in v.items() if a != "curve"} for k, v in single.items()},
               summary=summary, sa_grid=sa_grid, cd_order=dict(n=len(orders), min=min(order_J), max=max(order_J),
               frac_opt=float(np.mean(np.array(order_J) >= J_STAR - EPS)), evals_min=min(v["evals"] for v in orders.values()),
               evals_max=max(v["evals"] for v in orders.values())), lambda_rows=lam_rows, cd_theta=th_c)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res[k] for k in ("sa_grid", "cd_order")}, indent=1)); print(lam_rows)
    print("single:", {m: (round(v["best"], 3), v["evals"], v["first_hit"]) for m, v in single.items()})


if __name__ == "__main__":
    main()
