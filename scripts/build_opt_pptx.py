"""Builds optimization/Optimization_Presentation.pptx with the PowerPoint installed on this PC (COM).

    python scripts/optimization_study.py && python scripts/build_opt_pptx.py
"""
import json
import time
from pathlib import Path

import win32com.client

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "optimization" / "results.json").read_text())
S, ONE = R["summary"], R["single"]


def rgb(h):
    return ((h & 0xFF) << 16) | (h & 0xFF00) | (h >> 16)


NAVY, GREY, ACCENT, LIGHT, WHITE = rgb(0x1F3A5F), rgb(0x444444), rgb(0x2E86C1), rgb(0xEEF3F8), rgb(0xFFFFFF)
app = win32com.client.gencache.EnsureDispatch("PowerPoint.Application")
pres = app.Presentations.Add(True)
pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight = 960, 540
W, H = 960, 540
n = [0]
pct = lambda x: f"{100 * x:.0f}%"


def slide(title):
    n[0] += 1
    s = pres.Slides.Add(n[0], 12)
    bar = s.Shapes.AddShape(1, 0, 0, W, 78); bar.Fill.ForeColor.RGB = NAVY; bar.Line.Visible = False
    tb = s.Shapes.AddTextbox(1, 36, 12, W - 72, 56)
    r = tb.TextFrame.TextRange; r.Text = title; r.Font.Size = 30; r.Font.Bold = True; r.Font.Color.RGB = WHITE; r.Font.Name = "Calibri"
    tb.TextFrame.VerticalAnchor = 3
    ft = s.Shapes.AddTextbox(1, W - 120, H - 28, 100, 20)
    ft.TextFrame.TextRange.Text = str(n[0]); ft.TextFrame.TextRange.Font.Size = 11
    ft.TextFrame.TextRange.Font.Color.RGB = GREY; ft.TextFrame.TextRange.ParagraphFormat.Alignment = 3
    return s


def bullets(s, items, x=40, y=100, w=W - 80, h=H - 140, size=20):
    tb = s.Shapes.AddTextbox(1, x, y, w, h)
    tf = tb.TextFrame; tf.WordWrap = True
    tf.TextRange.Text = "\r".join(items)
    tf.TextRange.Font.Size = size; tf.TextRange.Font.Name = "Calibri"; tf.TextRange.Font.Color.RGB = GREY
    tf.TextRange.ParagraphFormat.Bullet.Visible = True; tf.TextRange.ParagraphFormat.Bullet.Character = 8226
    tf.TextRange.ParagraphFormat.SpaceAfter = 8
    return tb


def text(s, t, x, y, w, h, size=18, color=GREY):
    tb = s.Shapes.AddTextbox(1, x, y, w, h); tb.TextFrame.WordWrap = True
    r = tb.TextFrame.TextRange; r.Text = t; r.Font.Size = size; r.Font.Color.RGB = color; r.Font.Name = "Calibri"
    return tb


def pic(s, name, x, y, w=None, h=None):
    p = s.Shapes.AddPicture(str(ROOT / name), False, True, x, y, -1, -1)
    p.LockAspectRatio = True
    if w:
        p.Width = w
    elif h:
        p.Height = h
    p.Left, p.Top = x, y
    return p


def table(s, rows, x, y, w, colw, size=14, h=None):
    sh = s.Shapes.AddTable(len(rows), len(rows[0]), x, y, w, h or 30 * len(rows))
    t = sh.Table
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = t.Cell(i + 1, j + 1); r = c.Shape.TextFrame.TextRange
            r.Text = str(v); r.Font.Size = size; r.Font.Name = "Calibri"
            if i == 0:
                c.Shape.Fill.ForeColor.RGB = NAVY; r.Font.Color.RGB = WHITE; r.Font.Bold = True
            else:
                c.Shape.Fill.ForeColor.RGB = LIGHT if i % 2 else WHITE; r.Font.Color.RGB = GREY
    for j, cw in enumerate(colw):
        t.Columns(j + 1).Width = cw
    return sh


# 1 title ----------------------------------------------------------------------------------------
s = pres.Slides.Add(1, 12); n[0] = 1
bg = s.Shapes.AddShape(1, 0, 0, W, H); bg.Fill.ForeColor.RGB = NAVY; bg.Line.Visible = False
text(s, "Choosing Alert Parameters for Smart CCTV", 60, 120, 840, 70, 42, WHITE).TextFrame.TextRange.Font.Bold = True
text(s, "Formulation and comparison of optimisation algorithms", 60, 200, 840, 50, 26, rgb(0xDDE6F0))
text(s, "CS4101 - Introduction to Linear and Nonlinear Optimization - Phase 2\n25 November 2026", 60, 320, 840, 70, 18, rgb(0xBBCCE0))
text(s, "Tanya Sharma | BT24GCS667 | B.Tech 2024, AI & Data Science | Section A6 | Faculty: Dr. Sachin Dube", 60, 430, 840, 30, 16, rgb(0xBBCCE0))

s = slide("1. The problem to optimise")
bullets(s, [
    "Same real problem as our ML project: detect intrusions and crimes in CCTV video.",
    "The system raises an alert only if four thresholds are passed. Someone must choose them.",
    "Too loose: false alarms, guards ignore it. Too strict: real incidents are missed.",
    "This project is NOT model training. The object being optimised is the decision rule.",
    "Goal: formulate the choice mathematically, implement several algorithms, compare them, and improve one.",
], size=21)

s = slide("2. Mathematical formulation")
bullets(s, [
    "Variables x = (s, c, m, q): alert severity {1..5}; YOLO confidence {0.15..0.65}; frames in zone {1..30}; Gemini confidence {0..0.95}. |X| = 3,520 grid points.",
    "Per video v: a_v(x) = number of clips with type != normal, severity >= s, confidence >= q (the clips depend on c and m).",
    "F1(x) from 'a_v >= 1' versus the video label; FA(x) = alerts on normal videos.",
    "Maximise J(x) = F1(x) - 0.05 x FA(x)      (equivalently minimise f = -J).",
    "Constraint form: minimise -F1 subject to g1(x) = FA(x) <= 0 and bounds on each variable; g1 is handled by an exterior penalty.",
    "J is piecewise constant, non-differentiable, a black box (about 1 ms per evaluation from cached data).",
], size=18)

s = slide("3. Why gradient methods do not apply")
pic(s, "optimization/landscape_slices.png", 30, 95, w=900)
bullets(s, [
    "J versus each variable (others fixed at the CD solution): flat plateaus and sudden jumps, no slopes.",
    "The gradient is 0 almost everywhere. LP / simplex does not apply either: J is a counting function.",
    "922 of 3,520 points (26%) share the maximum J = 1.0: a plateau, not a single minimiser.",
], y=330, h=190, size=19)

s = slide("4. Algorithms (all written by hand)")
bullets(s, [
    "Coordinate Descent: for each coordinate i, x_i <- argmax over its grid of J(x_-i, v), only if strictly better. Stop when a full cycle changes nothing. 32 evaluations per cycle.",
    "Simulated Annealing: move one coordinate by 1-2 steps; accept if J does not drop, else with probability exp((J(y)-J(x))/T), T_k = T0 * a^k. T0 = 0.2 -> 0.005, 300 evaluations.",
    "Random Search: 300 uniform samples; a sanity baseline.",
    "Nelder-Mead on a rounded continuous relaxation: reflect, expand, contract, shrink the 5-point simplex. Stops on a plateau.",
    "Grid search: all 3,520 points; gives the true optimum J* = 1.0.",
], size=18)

s = slide("5. Proposed improvement: hybrid SA + CD")
bullets(s, [
    "Observation: CD is cheap but gets stuck on plateaus; SA never gets stuck but wastes evaluations.",
    "Hybrid: SA for 120 evaluations to reach a good region, then Coordinate Descent from SA's best point as a fast local polish.",
    "Test: 100 random starting points, same objective, same counters.",
    "Prediction: the reliability of SA with fewer evaluations than SA alone.",
], size=22)

s = slide("6. Experimental setup")
bullets(s, [
    "Same objective, grids, caches and evaluation counter for every algorithm. Fully offline.",
    "Experiment A: one run from the system's default point (3, 0.35, 3, 0).",
    "Experiment B: 100 random starting points per algorithm (fixed seeds); budget 300 for SA / RS / NM.",
    "Measures: best J; success = reaching J* = 1.0; evaluations; evaluations until J* first reached; time; convergence curves.",
    "Parameter studies: SA temperature and budget (12 settings), all 24 CD coordinate orders, penalty weight lambda.",
], size=20)

s = slide("7. Results: single run from the default point")
rows = [["Algorithm", "Best J", "Evals", "Evals to J*", "ms"]]
for m in ["CD", "SA", "RS", "NM", "NM-wide", "HYB", "GS"]:
    rows.append([m, f"{ONE[m]['best']:.3f}", ONE[m]["evals"], ONE[m]["first_hit"] or "-", f"{ONE[m]['time_ms']:.1f}"])
table(s, rows, 30, 95, 380, [90, 70, 70, 90, 60], 13, 260)
pic(s, "optimization/convergence_single.png", 430, 95, w=500)
bullets(s, ["Default J = 0.857 (Fighting002 missed). CD jumps to J* in 2 evaluations; standard Nelder-Mead stops at the start after 5."], x=30, y=380, w=390, h=140, size=15)

s = slide("8. Results: effect of the initial point (100 starts)")
rows = [["Algorithm", "Success", "Mean J", "Worst J", "Mean evals", "Median evals to J*"]]
for m in ["CD", "SA", "RS", "NM", "NM-wide", "HYB"]:
    med = S[m]["median_evals_to_opt"]
    rows.append([m, pct(S[m]["success_rate"]), f"{S[m]['mean_J']:.3f}", f"{S[m]['min_J']:.3f}", f"{S[m]['mean_evals']:.0f}", f"{med:.0f}" if med else "-"])
table(s, rows, 30, 95, 520, [110, 80, 70, 70, 90, 100], 14, 230)
pic(s, "optimization/initial_point_effect.png", 30, 340, h=175)
pic(s, "optimization/convergence_multistart.png", 565, 95, w=370)
bullets(s, ["SA, RS and HYB: 100% success. CD: 77%. Nelder-Mead: 21-28%. (Median evals counts successful runs only.)"], x=565, y=290, w=370, h=60, size=15)

s = slide("9. Effect of algorithm parameters")
sa = R["sa_grid"]
rows = [["SA: T0 / budget", "50", "150", "300"]] + [[t0] + [pct(sa[f"T0={t0}|budget={b}"]) for b in (50, 150, 300)] for t0 in ("0.01", "0.05", "0.2", "0.5")]
table(s, rows, 30, 100, 420, [150, 90, 90, 90], 15, 190)
bullets(s, [
    "SA: temperature hardly matters; budget does (about 85% at 50, 100% at 150 and above).",
    "CD order: all 24 orders give J = 1.0 in 65 evaluations from the default start.",
    "Penalty lambda in {0, 0.05, 0.2, 0.5}: same optimum, because the optimum has no false alarms (FA = 0).",
], x=30, y=320, w=900, h=200, size=18)
pic(s, "optimization/cd_order_effect.png", 560, 100, w=370)

s = slide("10. Analysis: why the differences?")
bullets(s, [
    "CD fails from 23% of starts: on a plateau no single-coordinate move changes J, and CD accepts only strict improvements. Every failure ended at J = 0.857 (Fighting002 not alerted).",
    "Nelder-Mead compares function values; on a plateau all 5 simplex values are equal, so it stops after 5 evaluations.",
    "SA and RS do not need local improvement, so plateaus do not trap them. RS is strong because 26% of all points are optimal.",
    "Same optimal VALUE, different optimal POINTS: 922 points tie.",
    "So the problem is easy for any global method; the ranking is limited evidence.",
], size=19)

s = slide("11. Improvement result")
rows = [["Method", "Success rate", "Mean evals", "Mean final J"]] + [[m, pct(S[m]["success_rate"]), f"{S[m]['mean_evals']:.0f}", f"{S[m]['mean_J']:.3f}"] for m in ["CD", "SA", "HYB"]]
table(s, rows, 40, 100, 520, [130, 130, 130, 130], 17, 150)
bullets(s, [
    "Hybrid raises CD's success from 77% to 100% using about half of SA's evaluations (153 vs 300). Supported by 100 runs.",
    "Honest limit: random search is also 100% reliable and reaches J* sooner (median 3 evaluations), so the hybrid is not shown to beat RS here.",
    "Expected to matter more on larger, less plateau-rich problems (not tested).",
], x=40, y=280, w=880, h=240, size=19)

s = slide("12. Limitations and conclusion")
bullets(s, [
    "One cached, in-sample objective with 3,520 points: brute force solves it in a few seconds. This is a study of methods, not a necessity.",
    "100 starts, no significance tests. The J = 1.0 optimum (severity 1) is in-sample and not trusted as a real setting (see the ML project).",
    "Conclusion: derivative-free global methods fit this problem; CD is cheapest but can stall; the SA + CD hybrid fixed CD's weakness.",
    "Future: a bigger search space (zone polygon, clip length), held-out videos, a smoothed objective, tie-aware CD, Bayesian optimisation.",
], size=20)

s = slide("Live demo")
bullets(s, [
    "Run: python scripts/optimization_study.py     (offline, 1-3 minutes)",
    "It prints the grid optimum and a table per algorithm, and writes the figures to optimization/.",
    "Quick run: python scripts/tune_coordinate_descent.py     (Coordinate Descent vs grid search, under 2 seconds)",
], size=20)

time.sleep(1)
out = ROOT / "optimization" / "Optimization_Presentation.pptx"
pres.SaveAs(str(out))
time.sleep(1)
for i in range(1, pres.Slides.Count + 1):
    pres.Slides(i).Export(str(ROOT / "optimization" / f"_slide{i:02d}.png"), "PNG", 960, 540)
print("saved", out)
try:
    pres.Close()
except Exception:
    pass
