"""Builds optimization/Optimization_Report.docx from optimization/results.json (run optimization_study.py first)."""
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "optimization" / "results.json").read_text())
S = R["summary"]; ONE = R["single"]

doc = Document()
doc.styles["Normal"].font.name = "Calibri"; doc.styles["Normal"].font.size = Pt(11)


def H(t, l=1): doc.add_heading(t, l)
def P(t, bold=False, italic=False):
    p = doc.add_paragraph(); r = p.add_run(t); r.bold = bold; r.italic = italic; return p
def B(items):
    for i in items: doc.add_paragraph(i, style="List Bullet")
def EQ(t):
    p = doc.add_paragraph(); r = p.add_run(t); r.font.name = "Cambria Math"; r.font.size = Pt(11.5)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after = Pt(4)
def IMG(path, w=6.0, cap=None):
    doc.add_picture(str(ROOT / path), width=Inches(w)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cap:
        c = doc.add_paragraph(cap); c.alignment = WD_ALIGN_PARAGRAPH.CENTER; c.runs[0].italic = True
def T(head, rows):
    t = doc.add_table(rows=1, cols=len(head)); t.style = "Light Grid Accent 1"
    for i, h in enumerate(head): t.rows[0].cells[i].text = h
    for r in rows:
        c = t.add_row().cells
        for i, v in enumerate(r): c[i].text = str(v)
    doc.add_paragraph()


pct = lambda x: f"{100 * x:.0f}%"
f3 = lambda x: "-" if x is None else f"{x:.1f}"

doc.add_heading("Choosing Alert Parameters for a Smart CCTV System: Formulation and Comparison of Optimisation Algorithms", 0)
P("CS4101 - Introduction to Linear and Nonlinear Optimization - Phase 2 Final Project Report")
P("Tanya Sharma, BT24GCS667, B.Tech 2024 AI & DS, Section A6. Faculty: Dr. Sachin Dube.      Evaluation date: 25 November 2026")

# ------------------------------------------------------------------------------ 1
H("1. Introduction and Problem Description")
P("The real-world problem (shared with our Machine Learning project) is perimeter intrusion and crime detection in CCTV video. "
  "A pipeline detects people and vehicles (YOLOv8), tracks them (ByteTrack), checks when they enter a restricted zone, and sends a short clip "
  "to a vision-language model (Gemini) that returns an event type, a severity from 1 to 5 and a confidence. An alert is raised when the answer passes a set of thresholds.")
P("The optimisation problem. Those thresholds are four numbers that someone must choose. If they are too loose the system raises false alarms and guards learn to ignore it; "
  "if they are too strict it misses real incidents. This report formulates that choice as a mathematical optimisation problem, solves it with several algorithms, "
  "compares them on the same problem, and proposes and tests an improvement. It does not repeat ML model training or report predictive accuracy; the ML project and this one share the data, "
  "but here the object being optimised is the decision rule.")
P("Applicability of method families (brief; the full survey was Phase 1):", bold=True)
T(["Method family", "Applicable?", "Reason for this problem"],
  [["Gradient descent, Newton, quasi-Newton", "No", "The objective is piecewise constant in the thresholds: the gradient is zero almost everywhere and undefined at the jumps."],
   ["Linear / quadratic programming, simplex", "No", "The objective is not linear or quadratic in the variables; it is a counting function."],
   ["Branch and bound, integer programming", "Not directly", "Needs an algebraic model of the objective; ours is a black box (a replay of cached detections and VLM answers)."],
   ["Grid / exhaustive search", "Yes (small grid)", "Only 3,520 points, so it gives the true optimum and serves as a reference. It does not scale to more parameters."],
   ["Coordinate descent", "Yes", "Derivative-free, one-dimensional searches, easy to explain. Implemented."],
   ["Simulated annealing, random search", "Yes", "Derivative-free global methods that tolerate plateaus. Implemented."],
   ["Nelder-Mead simplex", "Partly", "Derivative-free, but assumes a continuous landscape; we apply it to a rounded relaxation to see what happens. Implemented."]])

# ------------------------------------------------------------------------------ 2
H("2. Mathematical Formulation")
H("2.1 Decision variables", 2)
P("x = (s, c, m, q), where")
T(["Symbol", "Meaning", "Domain (grid G_i)", "Default"],
  [["s", "minimum Gemini severity for an alert", "{1, 2, 3, 4, 5}", "3"],
   ["c", "minimum YOLO box confidence", "{0.15, 0.20, ..., 0.65} (11 values)", "0.35"],
   ["m", "frames an object must stay in the zone to count as a breach", "{1, 2, 3, 5, 8, 12, 20, 30}", "3"],
   ["q", "minimum Gemini self-reported confidence", "{0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95}", "0 (no filter)"]])
P("The feasible set is the box-bounded discrete set X = G_1 x G_2 x G_3 x G_4, with |X| = 5 x 11 x 8 x 8 = 3,520 points. "
  "The bounds are the ranges that make operational sense (for example a YOLO confidence below 0.15 produces mostly noise).")
H("2.2 Parameters and data", 2)
P("The data are 6 videos v = 1..6 with video-level labels y_v (1 = incident, 0 = normal): Arson001, Assault001, Burglary001, Fighting002 (incident) and Normal_Videos_003, ShanghaiTech 01_0014 (normal). "
  "For each video the YOLO+ByteTrack detections were computed once at confidence 0.15 and cached; for every breach clip that any x could trigger, Gemini's answer (type, severity, confidence) was obtained once and cached (136 clips). "
  "A breach clip k of video v is triggered for a given (c, m) when a tracked object with box confidence at least c stays inside the zone for m consecutive frames (with the system's cooldown rules).")
H("2.3 Objective function", 2)
P("For a given x, let B_v(c, m) be the set of breach clips of video v. The number of alerts on video v is")
EQ("a_v(x) = sum over k in B_v(c, m) of  1[ type_k != normal  AND  severity_k >= s  AND  confidence_k >= q ]")
P("A video is predicted 'incident' when a_v(x) >= 1. With TP, FP, FN counted over the 6 videos,")
EQ("F1(x) = 2 TP / (2 TP + FP + FN),        FA(x) = sum over videos with y_v = 0 of a_v(x)   (alerts on normal videos)")
P("We want high F1 and few false-alarm alerts:")
EQ("maximise  J(x) = F1(x) - lambda * FA(x),  lambda = 0.05      (equivalently  minimise  f(x) = -J(x))")
H("2.4 Constraints", 2)
P("The natural constrained form is: minimise f(x) = -F1(x) subject to the inequality constraint g_1(x) = FA(x) <= 0 (no alert on a normal video) and the bound constraints "
  "g_2..g_9: lower and upper bounds on each variable. There are no equality constraints except that each variable must be a member of its grid, which is the discrete domain. "
  "We treat g_1 with an exterior penalty: infeasible points are not forbidden but pay lambda per unit of violation, giving the unconstrained form J above. "
  "Because the penalty is small, the penalised optimum could in principle be infeasible; the sensitivity study in Section 5.5 shows the result is the same for lambda from 0 to 0.5, and the optimum has FA = 0, so it is feasible.")
H("2.5 Properties and assumptions", 2)
B(["J takes only a few distinct values (F1 over 6 videos moves in steps), so it is piecewise constant with many plateaus: 922 of the 3,520 points (26%) share the maximum value J = 1.0.",
   "J is not differentiable and has no useful gradient; it is evaluated as a black box (about 1 ms per evaluation using the caches, so no network is needed).",
   "Assumptions: the video-level labels are correct; the cached Gemini answers are treated as deterministic (in reality a repeat call can differ); the same 6 videos are used for choosing and for scoring x. The last point means the optimum found is an in-sample optimum (discussed in Section 7)."])

# ------------------------------------------------------------------------------ 3
H("3. Selection and Description of the Optimisation Algorithms")
P("All algorithms below were written by hand in Python (no optimisation library) so that every update equation is explicit. They all see the same objective J through the same wrapper that counts evaluations.")
H("3.1 Coordinate Descent (CD)", 2)
P("Idea: improve one variable at a time with the others fixed. For cycle t = 1, 2, ... and each coordinate i = 1..4 in turn, do a one-dimensional line search over its grid:")
EQ("x_i  <-  argmax over v in G_i of J(x_1, ..., x_{i-1}, v, x_{i+1}, ..., x_4),   only if the best value is STRICTLY larger than J(x)")
P("Parameters: coordinate order (fixed as s, c, m, q), start point x0, max cycles 10. Stopping rule: a full cycle changes nothing, or 10 cycles. "
  "Cost: one cycle = 5 + 11 + 8 + 8 = 32 evaluations. Strength: simple, explainable, cheap per cycle. Weakness: on a plateau no single-coordinate move improves J, so it stops (it can be stuck at a non-optimal point).")
H("3.2 Simulated Annealing (SA)", 2)
P("Idea: random local moves, accepting some worse moves early so the search can leave plateaus and poor regions, then becoming greedy as the 'temperature' falls. "
  "A neighbour y of x changes one randomly chosen coordinate by 1 or 2 grid steps (clipped at the bounds). The Metropolis rule:")
EQ("accept y if J(y) >= J(x);  otherwise accept with probability  exp( (J(y) - J(x)) / T_k ),     T_k = T_0 * a^k,  a = (T_end / T_0)^(1/(N-1))")
P("Parameters: T_0 = 0.2, T_end = 0.005 (chosen so that a 1-video change in F1, about 0.1 to 0.2, is accepted early but not late), budget N = 300 evaluations, random seed. "
  "Stopping rule: the evaluation budget. The best point seen is returned.")
H("3.2.1 Random Search (RS) as a sanity baseline", 3)
P("Draw N = 300 points uniformly from X and keep the best. It uses no structure at all; any method that cannot beat it is not exploiting the problem.")
H("3.3 Nelder-Mead simplex (NM)", 2)
P("A derivative-free method for continuous problems. We apply it to a continuous relaxation: x in R^4 (in grid-index units), and J is evaluated at the rounded and clipped point. "
  "Keep n+1 = 5 points (the simplex), sort by f = -J, and with c = the centroid of the best n points and x_w the worst point:")
EQ("reflection  x_r = c + (c - x_w);   expansion  x_e = c + 2 (c - x_w);   contraction  x_c = c + 0.5 (x_w - c);   shrink  x_i <- x_1 + 0.5 (x_i - x_1)")
P("Stopping: budget 300 evaluations, or all simplex values equal (a plateau), or the simplex has collapsed. We run two variants: the standard small initial simplex (edge 0.05, which rounds to the same grid point), and a wide simplex (edge 2.5 grid steps).")
H("3.4 Grid search (GS)", 2)
P("Evaluate all 3,520 points. Exact within the grid; used as the reference optimum J*. Not a competitor on cost.")
H("3.5 Proposed extension: Hybrid SA + CD (HYB)", 2)
P("Motivated in Section 6: CD is cheap but can stall on a plateau; SA is robust to plateaus but wasteful near the end. The hybrid runs SA for a short budget (120 evaluations, T_0 = 0.2) to land in a good region, "
  "then runs CD from SA's best point as a fast local polish (typically 32 to 64 further evaluations).")

# ------------------------------------------------------------------------------ 4
H("4. Algorithm Implementation and Experimental Setup")
B(["Language and code: Python 3.13; NumPy; matplotlib. Files: scripts/tune_coordinate_descent.py (objective, CD, grid search), scripts/optimization_study.py (SA, RS, NM, hybrid and all experiments), scripts/tuning_common.py (cache replay). Run: python scripts/optimization_study.py (about 1 to 3 minutes, fully offline).",
   "Same problem for all: the same objective J, the same grids, the same caches, the same evaluation counter.",
   f"Experiment A (single run): every algorithm starts from the system's default point x0 = (3, 0.35, 3, 0) with seed 0.",
   f"Experiment B (initial points): {R['n_starts']} random start points x0 drawn uniformly from X (seeds fixed), each algorithm run once per start. Budget for SA, RS, NM: {R['budget']} evaluations; the hybrid uses {R['hyb_sa_budget']} for SA plus CD.",
   "Measures: best J found; success = reaching the true optimum J* = 1.0 (known from grid search); evaluations used; evaluations until J* was first reached; time. Convergence plots show the best-so-far J against the number of evaluations.",
   "Parameter studies: SA initial temperature and budget (12 settings x 100 starts); all 24 coordinate orders of CD; the penalty lambda in {0, 0.05, 0.2, 0.5}.",
   "A note on counting: a clipped SA move that stays on the same point is counted as an evaluation, which slightly overstates SA's cost."])

# ------------------------------------------------------------------------------ 5
H("5. Results and Comparative Evaluation")
H("5.1 Reference optimum", 2)
P(f"Grid search evaluated {R['n_grid']:,} points in {ONE['GS']['time_ms']/1000:.2f} s. The best value is J* = {R['J_star']:.2f}, reached at {R['grid_ties']} grid points (26% of the grid). "
  f"The system's default setting scores J = {R['J_default']:.3f} (F1 = 0.857: one incident video, Fighting002, produces no alert). "
  "So the possible gain is from 0.857 to 1.0, and all methods are measured against that.")
H("5.2 Single run from the default point", 2)
T(["Algorithm", "Best J", "Evaluations", "Evals until J* first reached", "Time (ms)"],
  [[m, f"{ONE[m]['best']:.3f}", ONE[m]["evals"], ONE[m]["first_hit"] if ONE[m]["first_hit"] else "-", f"{ONE[m]['time_ms']:.1f}"] for m in ["CD", "SA", "RS", "NM", "NM-wide", "HYB", "GS"]])
IMG("optimization/convergence_single.png", 5.7, "Figure 1: best J so far versus evaluations, starting from the default point.")
P("From the default point CD reaches J* after only 2 evaluations (the first line search, over severity, jumps from 3 to 1), then spends the rest of its 65 evaluations confirming that nothing better exists. "
  "The standard NM stops after 5 evaluations on the starting plateau without moving; the wide-simplex NM finds J* after 6 evaluations. SA, RS and the hybrid also reach J* within 5 evaluations; "
  "their remaining budget is spent because they have no way to know that J* has been reached.")
H("5.3 Effect of the initial point (100 random starts)", 2)
T(["Algorithm", "Success rate (reach J*)", "Mean final J", "Worst final J", "Mean evals used", "Median evals until J*", "Mean time (ms)"],
  [[m, pct(S[m]["success_rate"]), f"{S[m]['mean_J']:.3f}", f"{S[m]['min_J']:.3f}", f"{S[m]['mean_evals']:.0f}", f3(S[m]["median_evals_to_opt"]), f"{S[m]['mean_time_ms']:.1f}"]
   for m in ["CD", "SA", "RS", "NM", "NM-wide", "HYB"]])
P("Note: 'Median evals until J*' is computed over the runs that did reach J* only. Nelder-Mead's value of 1 means that the few runs that succeeded started on an optimal point; it does not mean it is fast.", italic=True)
IMG("optimization/convergence_multistart.png", 5.7, "Figure 2: mean best-so-far J over 100 random starts. SA and HYB share the first 120 evaluations (same seeds), so their curves overlap.")
IMG("optimization/initial_point_effect.png", 6.0, "Figure 3: success rate and median cost to reach the optimum.")
H("5.4 Effect of algorithm parameters", 2)
P("Simulated annealing: success rate over 100 starts for each (T_0, budget):")
sa = R["sa_grid"]
T(["T_0 \\ budget", "50", "150", "300"],
  [[t0] + [pct(sa[f"T0={t0}|budget={b}"]) for b in (50, 150, 300)] for t0 in ("0.01", "0.05", "0.2", "0.5")])
P(f"The initial temperature has almost no effect (85 to 87% at budget 50, 100% at 150 and above); the budget is what matters. "
  f"Coordinate order in CD: all {R['cd_order']['n']} orders reach J = {R['cd_order']['max']:.2f} from the default start with exactly {R['cd_order']['evals_min']} evaluations, so order does not matter there. "
  "(From random starts the order could matter; we did not test that.)")
IMG("optimization/landscape_slices.png", 6.4, "Figure 4: one-dimensional slices of J through the CD solution. Plateaus and jumps, no slopes.")
H("5.5 Effect of the penalty lambda", 2)
T(["lambda", "Grid-search best J", "Tied optimal points", "CD best J (from default)"],
  [[r["lam"], f"{r['grid_best']:.3f}", r["grid_ties"], f"{r['cd_best']:.3f}"] for r in R["lambda_rows"]])
P("The optimum is identical for every lambda, because the optimal points have no false-alarm alerts (FA = 0), so the penalty term vanishes there. The penalty only shapes the landscape at infeasible points.")

# ------------------------------------------------------------------------------ 6
H("6. Critical Analysis and Proposed Improvement")
H("6.1 Which algorithm performed better, and in what sense?", 2)
B([f"Reliability: SA, RS and the hybrid reach J* from every one of 100 random starts (100%); CD reaches it from {pct(S['CD']['success_rate'])}; NM from {pct(S['NM']['success_rate'])} (standard) and {pct(S['NM-wide']['success_rate'])} (wide).",
   f"Cost to first reach J*: RS needs a median of {S['RS']['median_evals_to_opt']:.0f} evaluations, CD {S['CD']['median_evals_to_opt']:.0f}, SA and the hybrid {S['SA']['median_evals_to_opt']:.1f}. "
   "These are all tiny compared with the 3,520 of grid search (more than 100 times fewer).",
   f"Cost to finish: CD stops by itself after {S['CD']['mean_evals']:.0f} evaluations on average (a stopping rule that knows when to quit). RS, SA use the whole budget of 300; the hybrid uses {S['HYB']['mean_evals']:.0f}.",
   "So there is no single winner. CD is the cheapest and self-terminating but not always right; SA/RS/HYB are always right but must spend a fixed budget."])
H("6.2 Did the algorithms converge to the same solution?", 2)
P("They reach the same optimal value J* = 1.0 but not the same point: 922 grid points tie, and different algorithms stop at different ones (CD from default stops at severity 1, YOLO confidence 0.35, 3 frames, no confidence filter). "
  "The optimum is a large flat plateau, not a unique minimiser, which is why 'same solution' has to be read as 'same objective value'. "
  "When an algorithm did not reach J*, it ended at J = 0.857 (or lower for NM), which is the plateau where Fighting002 yields no alert.")
H("6.3 What explains the differences?", 2)
B(["CD fails when it starts on a plateau where no single-coordinate move changes J. Example from our runs: start (severity 5, conf 0.45, 20 frames, q = 0) ends at the same point with J = 0.857, because changing any one variable leaves the set of alerts unchanged. "
   "CD only accepts strict improvements, so it stops. The 23 failures all ended at J = 0.857 or below with a missing alert on Fighting002.",
   "NM builds its moves from differences of function values. On a plateau all 5 simplex values are equal, so the rule 'stop when values are equal' fires after 5 evaluations (success only 21%). A wide simplex helps (28%) but rounding the relaxation still creates many identical vertices.",
   "SA and RS do not rely on local improvement, so plateaus do not trap them. RS is so good here because 26% of all points are optimal: the probability that a random point is optimal is 0.26, so 300 draws miss it with probability 0.74^300, effectively zero.",
   "Consequence: the problem is easy for any global method. This says more about the (small, plateau-rich) problem than about the quality of the algorithms."])
H("6.4 Proposed improvement: hybrid SA + CD", 2)
P("Justification. CD's weakness is getting stuck on a plateau; SA's weakness is that it wastes evaluations after reaching a good region and does not know when to stop. "
  "The hybrid gives CD a good start (SA, 120 evaluations) and uses CD's cheap line searches to finish.")
T(["Method", "Success rate", "Mean evals", "Mean final J"],
  [[m, pct(S[m]["success_rate"]), f"{S[m]['mean_evals']:.0f}", f"{S[m]['mean_J']:.3f}"] for m in ["CD", "SA", "HYB"]])
P(f"Result: the hybrid raises CD's success rate from {pct(S['CD']['success_rate'])} to 100% and uses {S['HYB']['mean_evals']:.0f} evaluations on average, about half of SA's 300. "
  "This improvement over CD is supported by the computation (100 starts). Two honest qualifications: (1) random search with 300 evaluations is also 100% reliable and finds J* sooner, so the hybrid is not shown to beat RS on this problem; "
  "(2) the hybrid's CD polish adds no extra value once SA has already found the optimum; its benefit would appear on harder, less plateau-rich objectives, which we did not test.")
H("6.5 Limitations of the implemented algorithms", 2)
B(["All results come from one cached, in-sample objective with 3,520 points; the problem can be solved exactly by brute force in a few seconds, so the comparison is a study of methods, not a necessity.",
   "100 random starts per method; no confidence intervals or significance tests. Differences like 85% versus 87% at small budgets are within noise.",
   "CD uses a fixed coordinate order and strict-improvement acceptance; a tie-aware variant (accept equal moves, randomise the order) could escape some plateaus. Not tested.",
   "SA's temperature schedule and move set were chosen by us, with only a limited sensitivity study; NM is applied outside its intended (continuous, smooth) setting on purpose.",
   "The optimum J = 1.0 is an in-sample value: the same 6 videos select and score x. The ML report shows that the severity-1 optimum is not trustworthy as a real-world setting (it relies on counting a low-severity 'intrusion' alert on Fighting002 for the wrong reason)."])

# ------------------------------------------------------------------------------ 7
H("7. Conclusion and Future Scope")
P("We formulated the choice of alert thresholds of a CCTV system as a box-bounded discrete optimisation of a piecewise-constant black-box objective J = F1 - lambda x (false-alarm alerts), implemented Coordinate Descent, "
  "Simulated Annealing, Random Search, Nelder-Mead and Grid Search by hand, and compared them on the same problem. All methods can improve on the default (J = 0.857); the true optimum is J = 1.0 on a plateau of 922 points. "
  "Derivative-based methods do not apply. CD is the cheapest but fails from 23% of starts because it stalls on plateaus; Nelder-Mead fails most often for the same reason; SA, RS and the proposed SA + CD hybrid never failed in 100 starts. "
  "The hybrid fixed CD's weakness with about half of SA's evaluations. The main caution is that the problem is small and easy, so the ranking of algorithms is limited evidence.")
B(["Enlarge the search space (zone polygon coordinates, clip length, cooldowns) so brute force is no longer possible; this is where the methods would really differ.",
   "Evaluate on a held-out set of videos so the optimum reflects generalisation, not fit to 6 clips; use a smoothed objective (for example the mean of the per-video margin between severity and threshold) to give gradient-like information.",
   "Try a tie-aware CD, genetic algorithms or Bayesian optimisation for noisy VLM answers; treat Gemini's randomness explicitly with repeated evaluations."])

# ------------------------------------------------------------------------------ 8
H("8. References")
B(["Nocedal, J., Wright, S. Numerical Optimization, 2nd ed., Springer, 2006 (coordinate descent, Nelder-Mead, penalty methods).",
   "Kirkpatrick, S., Gelatt, C. D., Vecchi, M. P. Optimization by Simulated Annealing. Science 220, 1983.",
   "Nelder, J. A., Mead, R. A Simplex Method for Function Minimization. The Computer Journal 7, 1965.",
   "Bergstra, J., Bengio, Y. Random Search for Hyper-Parameter Optimization. JMLR 13, 2012.",
   "Wright, S. J. Coordinate Descent Algorithms. Mathematical Programming 151, 2015.",
   "Sultani, Chen, Shah. Real-world Anomaly Detection in Surveillance Videos. CVPR 2018 (UCF-Crime).",
   "Project code: https://github.com/Tanya-74/SmartCCTV_Project (scripts/optimization_study.py)."])

out = ROOT / "optimization" / "Optimization_Report.docx"
doc.save(out); print("saved", out)
