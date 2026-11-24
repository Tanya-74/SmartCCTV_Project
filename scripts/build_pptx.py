"""Builds report/Final_Presentation.pptx using the PowerPoint installed on this PC (COM). Run build after evaluate_baselines.py.

    python scripts/build_pptx.py
"""
import json
from pathlib import Path

import win32com.client

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "report" / "results.json").read_text())
B = R["baselines"]

NAVY, GREY, RED, GREEN, LIGHT = 0x5B2E1F, 0x555555, 0x2B39C0, 0x449E1E, 0xF7F1EC   # BGR ints for COM


def rgb(h):  # 0xRRGGBB -> BGR int
    return ((h & 0xFF) << 16) | (h & 0xFF00) | (h >> 16)


NAVY, GREY, RED, GREEN, LIGHT, ACCENT = rgb(0x1F3A5F), rgb(0x444444), rgb(0xC0392B), rgb(0x1E8449), rgb(0xEEF3F8), rgb(0x2E86C1)

app = win32com.client.gencache.EnsureDispatch("PowerPoint.Application")
pres = app.Presentations.Add(True)
pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight = 960, 540
W, H = 960, 540
n = [0]


def slide(title, subtitle=None):
    n[0] += 1
    s = pres.Slides.Add(n[0], 12)  # blank
    bar = s.Shapes.AddShape(1, 0, 0, W, 78); bar.Fill.ForeColor.RGB = NAVY; bar.Line.Visible = False
    tb = s.Shapes.AddTextbox(1, 36, 12, W - 72, 56)
    r = tb.TextFrame.TextRange; r.Text = title; r.Font.Size = 30; r.Font.Bold = True; r.Font.Color.RGB = rgb(0xFFFFFF); r.Font.Name = "Calibri"
    tb.TextFrame.VerticalAnchor = 3
    ft = s.Shapes.AddTextbox(1, W - 120, H - 28, 100, 20)
    ft.TextFrame.TextRange.Text = f"{n[0]}"; ft.TextFrame.TextRange.Font.Size = 11; ft.TextFrame.TextRange.Font.Color.RGB = GREY
    ft.TextFrame.TextRange.ParagraphFormat.Alignment = 3
    return s


def bullets(s, items, x=40, y=100, w=W - 80, h=H - 140, size=20):
    tb = s.Shapes.AddTextbox(1, x, y, w, h)
    tf = tb.TextFrame; tf.WordWrap = True
    tf.TextRange.Text = "\r".join(items)
    tf.TextRange.Font.Size = size; tf.TextRange.Font.Name = "Calibri"; tf.TextRange.Font.Color.RGB = GREY
    tf.TextRange.ParagraphFormat.Bullet.Visible = True
    tf.TextRange.ParagraphFormat.Bullet.Character = 8226
    tf.TextRange.ParagraphFormat.SpaceAfter = 8
    return tb


def text(s, t, x, y, w, h, size=18, bold=False, color=GREY, align=1):
    tb = s.Shapes.AddTextbox(1, x, y, w, h); tb.TextFrame.WordWrap = True
    r = tb.TextFrame.TextRange; r.Text = t; r.Font.Size = size; r.Font.Bold = bold; r.Font.Color.RGB = color; r.Font.Name = "Calibri"
    r.ParagraphFormat.Alignment = align
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


def table(s, rows, x, y, w, colw=None, size=14, h=None):
    nr, nc = len(rows), len(rows[0])
    sh = s.Shapes.AddTable(nr, nc, x, y, w, h or 30 * nr)
    t = sh.Table
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = t.Cell(i + 1, j + 1); r = c.Shape.TextFrame.TextRange
            r.Text = str(v); r.Font.Size = size; r.Font.Name = "Calibri"
            if i == 0:
                c.Shape.Fill.ForeColor.RGB = NAVY; r.Font.Color.RGB = rgb(0xFFFFFF); r.Font.Bold = True
            else:
                c.Shape.Fill.ForeColor.RGB = LIGHT if i % 2 else rgb(0xFFFFFF); r.Font.Color.RGB = GREY
    if colw:
        for j, cw in enumerate(colw):
            t.Columns(j + 1).Width = cw
    return sh


def notes(s, t):
    s.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = t


# 1 ------------------------------------------------------------------------------------------ title
s = pres.Slides.Add(1, 12); n[0] = 1
bg = s.Shapes.AddShape(1, 0, 0, W, H); bg.Fill.ForeColor.RGB = NAVY; bg.Line.Visible = False
text(s, "Smart CCTV", 60, 130, 840, 70, 54, True, rgb(0xFFFFFF))
text(s, "Real-Time Perimeter Intrusion and Crime Detection using a Vision-Language Model", 60, 215, 840, 90, 28, False, rgb(0xDDE6F0))
text(s, "Machine Learning Project - Phase 2 Final Evaluation\nNIIT University, Department of Computer Science and Engineering\n25 November 2026", 60, 340, 840, 90, 18, False, rgb(0xBBCCE0))
text(s, "Team: [add names and roll numbers]", 60, 450, 840, 30, 16, False, rgb(0xBBCCE0))
notes(s, "Introduce the project in one sentence: a system that watches CCTV video and raises an alert only when something that looks like a real incident enters a restricted zone.")

# 2 ------------------------------------------------------------------------------------------ problem
s = slide("1. The problem")
bullets(s, [
    "A guard cannot watch many camera feeds all day.",
    "A simple 'something entered the area' alarm fires constantly, so people learn to ignore it.",
    "Goal: alert only when the footage looks like a real incident, and say in one sentence what happened.",
    "Unit of analysis: one zone-entry moment, seen as a 6-second clip (4 s before, 2 s after).",
    "Output: event type + severity 1-5 + description + confidence. Alert if severity >= 3.",
    "Success measured by video-level F1 of 'alert / no alert' against the dataset labels, compared with two baselines.",
], size=21)
notes(s, "Phase 1 style question: what exactly is the problem and who has it. Stakeholder: a security guard / control room operator.")

# 3 ------------------------------------------------------------------------------------------ dataset
s = slide("2. Dataset (what we actually hold)")
rows = [["Video", "Label", "Frames", "Sec", "Size", "Breaches"]]
for v in R["videos"]:
    rows.append([v["video"].replace("_x264", ""), v["label"], v["frames"], v["seconds"], f'{v["width"]}x{v["height"]}', v["breaches"]])
table(s, rows, 40, 100, 880, [310, 110, 110, 100, 130, 120], 16, 230)
bullets(s, [
    "Sources: UCF-Crime (Sultani et al., CVPR 2018) and ShanghaiTech Campus, via Kaggle. A small sample only: 6 videos, about 16,300 frames.",
    "Labels are per video, from file names (Arson / Assault / Burglary / Fighting = incident). 4 incident, 2 normal.",
    "Low resolution (320x240); no Robbery or Stealing clips in our sample.",
], y=350, h=170, size=17)
notes(s, "Be upfront: this is a small demonstration set. Labels say which video has a crime but not when it happens.")

# 4 ------------------------------------------------------------------------------------------ pipeline
s = slide("3. Method: a pipeline, no training")
stages = [("YOLOv8s", "finds people\nand vehicles"), ("ByteTrack", "gives each one\na stable ID"), ("Zone trigger", "inside the zone\nfor 3+ frames?"),
          ("Gemini VLM", "reads 6 key frames,\nreturns JSON"), ("Alert engine", "severity >= 3\n-> alert"), ("Dashboard", "live feed via\nWebSocket")]
bw, gap, x0 = 135, 14, 36
for i, (a, b) in enumerate(stages):
    x = x0 + i * (bw + gap)
    box = s.Shapes.AddShape(5, x, 120, bw, 120); box.Fill.ForeColor.RGB = ACCENT if i != 3 else RED; box.Line.Visible = False
    r = box.TextFrame.TextRange; r.Text = a + "\r" + b; r.Font.Size = 15; r.Font.Color.RGB = rgb(0xFFFFFF); r.Font.Name = "Calibri"
    r.Paragraphs(1).Font.Bold = True; r.Paragraphs(1).Font.Size = 18
    if i < len(stages) - 1:
        ar = s.Shapes.AddTextbox(1, x + bw - 4, 160, 24, 30); ar.TextFrame.TextRange.Text = ">"; ar.TextFrame.TextRange.Font.Size = 22; ar.TextFrame.TextRange.Font.Color.RGB = GREY
bullets(s, [
    "Why pretrained and not trained: labels are per video and only 6 videos exist, far too few to train a detector or classifier. A zero-shot VLM needs no training data.",
    "Only moments of interest go to Gemini (a slow, paid API), not every frame.",
    "Inputs: uploaded video or a live RTSP stream (tested with a local fake IP camera at ~9.6 fps).",
    "Red box = the only part that needs the internet.",
], y=270, h=250, size=19)
notes(s, "If asked why no training: be direct. The learning problem we studied is the decision layer, i.e. which thresholds turn detections and VLM answers into alerts.")

# 5 ------------------------------------------------------------------------------------------ EDA
s = slide("4. Exploratory analysis")
pic(s, "report/eda_breaches_alerts.png", 30, 90, 560)
pic(s, "report/eda_gemini_outputs.png", 30, 300, 560)
bullets(s, [
    "Breaches are very uneven: Arson001 has 11; Normal_Videos_003 has 0 (nearly empty scene, 2 person boxes in 2,822 frames).",
    "The 'normal' class has almost no hard cases. The only one is ShanghaiTech (1 breach, Gemini says 'normal').",
    "Arson001 is mostly vehicle boxes: the fire is not detectable by YOLO, only by Gemini.",
    "Gemini never returned severity 3, and its confidence is always 0.80-1.00.",
], x=610, y=95, w=320, h=420, size=15)
notes(s, "Figure left-top: breaches vs alerts per video. Left-bottom: what Gemini said. Point out the thin normal class and the non-informative confidence.")

# 6 ------------------------------------------------------------------------------------------ tuning
s = slide("5. Tuning with Coordinate Descent")
bullets(s, [
    "Tuned 4 decision parameters: alert severity, YOLO confidence, min frames in zone, min Gemini confidence.",
    "Coordinate Descent, written by hand: change one parameter at a time (1-D grid line search), keep it only if strictly better, repeat until a full cycle changes nothing.",
    "Objective: J = F1 - 0.05 x (alerts on normal videos). All 136 Gemini answers cached, so tuning runs offline in under a second.",
    "Result: J = 1.00 in 65 evaluations. Grid search: same J in 3,520 evaluations (54x more).",
    "But 922 of 3,520 grid points tie, and tuning and scoring used the same 6 videos.",
    "So we kept the defaults. The tuned severity-1 value is reported as an experiment, not adopted.",
], x=40, y=95, w=470, h=430, size=17)
pic(s, "tuning_coordinate_descent.png", 520, 120, 410)
notes(s, "This is the honest answer to 'did tuning help?': it found a better score, but the data cannot justify changing the defaults.")

# 7 ------------------------------------------------------------------------------------------ results
s = slide("6. Results and comparison with baselines")
rows = [["System", "TP", "FP", "FN", "TN", "Prec.", "Recall", "F1"]]
for k, v in B.items():
    rows.append([k.replace("Ours, severity>=1 (tuning result, NOT adopted)", "Tuned: severity >= 1 (not adopted)"), v["TP"], v["FP"], v["FN"], v["TN"], v["precision"], v["recall"], v["F1"]])
table(s, rows, 30, 95, 900, [380, 60, 60, 60, 60, 90, 100, 90], 14, 200)
pic(s, "report/baseline_comparison.png", 30, 310, 360)
bullets(s, [
    "Our system (defaults): F1 0.857, no false alarms, 1 miss (Fighting002).",
    "Beats always-alert (0.800) by +0.057, but NOT the zone-breach-only baseline (0.889): -0.032. That is one video, so it is not significant.",
    "What the VLM adds: zero false alarms on normal videos, plus an event type and a written description for every alert.",
], x=410, y=315, w=520, h=210, size=16)
notes(s, "Say clearly: we did not beat the zone-only baseline on this tiny set. The VLM's value here is fewer false alarms and explanations.")

# 8 ------------------------------------------------------------------------------------------ insights
s = slide("7. What the results mean")
bullets(s, [
    "Fighting002 was missed because the trigger only fires on zone entry; the clips sent to Gemini probably never showed the fight. This is a trigger-design limit, not a Gemini mistake (our explanation, not proven).",
    "Lowering the threshold to severity 1-2 'fixes' it, but for the wrong reason (an intrusion label, not the fight) and would likely cause false alarms on busy scenes.",
    "Gemini confidence (0.80-1.00 for every clip) separates nothing, so a confidence filter is useless here.",
    "The VLM helps most where YOLO is blind (fire in Arson001) and when dismissing harmless breaches (ShanghaiTech).",
    "A higher score is not the point: with 6 videos the honest claim is 'works as a demonstration', not 'beats the baseline'.",
], size=19)
notes(s, "Critical-insights slide: why, not just what.")

# 9 ------------------------------------------------------------------------------------------ limitations
s = slide("8. Limitations")
bullets(s, [
    "6 videos, video-level labels; tuned and scored on the same data (no held-out test set).",
    "Normal class is nearly empty of people: false-alarm behaviour on busy normal scenes is untested.",
    "Triggers only on zone entry; low-resolution footage; no Robbery / Stealing.",
    "Needs internet and a Google API key for classification; the API can be overloaded (we saw 429 / 503 / 504). Offline: detection and tracking still run, but no alerts are classified.",
    "VLM answers vary between similar clips; confidence is not calibrated.",
    "Alerts stored in a JSON file; privacy of monitoring people not addressed.",
], size=19)

# 10 ------------------------------------------------------------------------------------------ conclusion
s = slide("9. Conclusion and future work")
bullets(s, [
    "Problem addressed as a working system: upload or live RTSP in, described alerts on a live dashboard out.",
    "Success criterion: met against always-alert (0.857 vs 0.800), not met against zone-breach-only (0.857 vs 0.889).",
    "Next: full UCF-Crime test split with a held-out set; alerts per hour on long normal footage.",
    "Add triggers that do not depend on a zone (sudden motion, crowding) so fights are not missed.",
    "Run a local VLM so it works offline and without per-call cost; calibrate severity; use a database.",
], size=20)
text(s, "Code and README: github.com/Tanya-74/SmartCCTV_Project", 40, 470, 880, 30, 16, False, ACCENT)

# 11 ------------------------------------------------------------------------------------------ demo
s = slide("Live demo")
bullets(s, [
    "1. Dashboard at http://127.0.0.1:8000: upload Assault001_x264.mp4 and watch alerts appear (needs internet).",
    "2. Live mode: fake RTSP camera at rtsp://127.0.0.1:8554/cam1 -> 'Connect a live camera'.",
    "3. No internet? Show the saved alerts already on the dashboard, and run: python scripts/tune_coordinate_descent.py (fully offline).",
], size=20)

out = ROOT / "report" / "Final_Presentation.pptx"
import time
time.sleep(1)
pres.SaveAs(str(out))
time.sleep(1)
for i in range(1, pres.Slides.Count + 1):
    pres.Slides(i).Export(str(ROOT / "report" / f"_slide{i:02d}.png"), "PNG", 960, 540)
pres.Close()
print("saved", out)
