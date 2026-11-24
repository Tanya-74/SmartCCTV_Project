"""Builds report/Final_Project_Report.docx from report/results.json + charts (run evaluate_baselines.py first)."""
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "report" / "results.json").read_text())
CD = json.loads((ROOT / "experiments" / "tuning_results.json").read_text())

doc = Document()
st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)


def H(t, lvl=1): doc.add_heading(t, lvl)
def P(t, bold=False):
    p = doc.add_paragraph(); r = p.add_run(t); r.bold = bold; return p
def B(items):
    for i in items: doc.add_paragraph(i, style="List Bullet")
def IMG(name, w=6.2, cap=None):
    doc.add_picture(str(ROOT / name), width=Inches(w)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cap:
        c = doc.add_paragraph(cap); c.alignment = WD_ALIGN_PARAGRAPH.CENTER; c.runs[0].italic = True
def T(head, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(head)); t.style = "Light Grid Accent 1"
    for i, h in enumerate(head): t.rows[0].cells[i].text = h
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r): cells[i].text = str(v)
    doc.add_paragraph()


# ------------------------------------------------------------------ title
t = doc.add_heading("Smart CCTV: Real-Time Perimeter Intrusion and Crime Detection using a Vision-Language Model", 0)
P("NIIT University - Department of Computer Science and Engineering - Machine Learning Project, Phase 2 Final Report")
P("Tanya Sharma, BT24GCS667, B.Tech 2024 AI & DS, Section A6. Faculty: Dr. Sachin Dube.   Date of evaluation: 25 November 2026")

# ------------------------------------------------------------------ 1
H("1. Problem Statement")
P("Specification statement. For each moment when a person or vehicle enters a restricted zone in a CCTV video, "
  "given a 6-second clip around that moment (4 s before, 2 s after), predict whether it is a security incident "
  "(event type plus severity 1 to 5, alert if severity is 3 or more), evaluated by video-level F1 of 'alert / no alert' "
  "against the dataset's video labels, compared with a zone-breach-only baseline (F1 0.889) and an always-alert baseline (F1 0.800).")
P("The real-world problem. A guard cannot watch many camera feeds all day. Most motion in a feed is harmless, so a "
  "simple 'something entered the area' alarm fires constantly and gets ignored. We want a system that raises an "
  "alert only when the footage looks like a real incident (intrusion, assault, theft, vandalism, arson ...), and "
  "explains in a sentence what it saw.")
P("What the system does. YOLOv8 finds people and vehicles; ByteTrack follows each one; when a tracked object stays inside "
  "a drawn restricted zone, the system saves a short clip and sends 6 key frames to Gemini, which returns a structured "
  "answer (event type, severity, description, confidence). Severity 3 or more becomes an alert on a live dashboard.")
P("Note on the ML formulation. No model is trained in this project: YOLOv8s and Gemini are pretrained. The learning "
  "problem we studied is the decision layer: which thresholds turn raw detections and VLM answers into alerts, "
  "and does the VLM stage actually improve on the cheap baselines.")

# ------------------------------------------------------------------ 2
H("2. Dataset Description")
P("Source: UCF-Crime (Sultani et al., CVPR 2018) and ShanghaiTech Campus, downloaded through Kaggle. We hold a small sample, not the full datasets.")
T(["Video", "Label", "Frames", "Seconds", "Resolution", "Zone breaches"],
  [[v["video"], v["label"], v["frames"], v["seconds"], f'{v["width"]}x{v["height"]}', v["breaches"]] for v in R["videos"]])
B(["Labels are video-level and come from the dataset's own file naming (Arson / Assault / Burglary / Fighting = incident; Normal and ShanghaiTech = normal). They do not say when in the video the incident happens.",
   "6 videos in total (4 incident, 2 normal), about 16,300 frames. Class balance: 67% incident, 33% normal.",
   "UCF-Crime clips are 320x240 at 30 fps: low resolution, which limits detection of small people and faces.",
   "Robbery and Stealing videos were not available in the sample we could download; ShanghaiTech is one short 6-second sequence."])

# ------------------------------------------------------------------ 3
H("3. Data Preparation")
B(["Frames are read with OpenCV. No frames are resized by us except YOLO's internal 640-pixel resize.",
   "Restricted zone: a polygon in normalised 0-1 coordinates, tested at each object's foot point. For the evaluation we use the whole frame as the zone, because the UCF cameras are different in every video and one fixed polygon cannot fit them all.",
   "Only COCO classes person, bicycle, car, motorcycle, bus, truck are kept; everything else is ignored.",
   "To make tuning cheap and repeatable, YOLO + ByteTrack was run once per video at a low confidence (0.15) and every box was cached; stricter confidence values are simulated later by dropping weak boxes. All 136 distinct clips any setting could trigger were sent to Gemini once and cached (experiments/gemini_cache.json).",
   "Leakage check: the clip sent to Gemini contains only pixels from the video. The file name and label never enter the model input; labels are used only in the scoring code (tuning_common.label_of)."])

# ------------------------------------------------------------------ 4
H("4. Exploratory Data Analysis")
IMG("report/eda_breaches_alerts.png", cap="Figure 1: zone breaches found, and alerts raised at the default threshold, per video.")
B(["Breaches are very uneven: Arson001 has 11 (a street with many cars), Normal_Videos_003 has 0 (almost empty: only 2 person boxes in 2,822 frames). The 'normal' class is therefore thin and quiet; it contains almost no hard negatives.",
   "ShanghaiTech has 350 person boxes in 150 frames (a busy walkway) and produced 1 breach, which Gemini called 'normal'. This is the only normal clip the VLM actually had to judge.",
   "Arson001 is dominated by vehicle boxes (6,623) and very few people (1,042): the incident (fire) is not something YOLO can detect; only Gemini can describe it."])
IMG("report/eda_gemini_outputs.png", cap="Figure 2: what Gemini said about the %d breach clips at default settings." % R["clips_scored"])
B([f'Event types: {R["event_types"]}. Severity counts: {R["severities"]}. Gemini never returned severity 3, so thresholds 3 and 4 behave identically here.',
   f'Gemini confidence only ranges from {R["gemini_conf_min"]} to {R["gemini_conf_max"]}: it is almost always very sure, so the confidence filter has little to work with.'])

# ------------------------------------------------------------------ 5
H("5. ML Methodology")
T(["Stage", "Tool", "Why"],
  [["Detect", "YOLOv8s (pretrained COCO)", "Fast, runs on the laptop GPU (RTX 3050 6 GB), detects people and vehicles."],
   ["Track", "ByteTrack", "Gives each object a stable ID so one person is not analysed again every frame."],
   ["Trigger", "Zone polygon + min frames in zone + cooldowns", "Avoids sending every frame to a paid, slow API: only moments of interest go to the VLM."],
   ["Understand", "Gemini (google-genai), structured JSON output", "A VLM can describe actions (fighting, fire, theft) that a box detector cannot."],
   ["Decide", "Alert if event is not 'normal' and severity >= 3", "Simple, explainable rule that a user can adjust."],
   ["Serve", "FastAPI + WebSocket dashboard, RTSP live input", "Real-time use: upload mode and live-camera mode."]])
IMG("report/pipeline_diagram.png", w=6.4, cap="Figure 3: the complete pipeline, from camera input to dashboard alert.")
IMG("report/input_output.png", w=6.4, cap="Figure 4: example input frame, the detector and tracker output with the restricted zone, and the alert shown to the user.")
P("Why a pretrained pipeline and not a trained model? Labelled incident data with locations in time is not available to us "
  "(labels are per video), and 6 videos is far too few to train a detector or classifier. A zero-shot VLM needs no training data, "
  "which suits this setting. The cost is that we depend on an online service (see Limitations).")

# ------------------------------------------------------------------ 6
H("6. Model Training and Tuning")
P("There is no training. We tuned four decision parameters with a hand-written Coordinate Descent (one parameter at a time, 1-D grid line search, repeat until nothing improves):")
T(["Parameter", "Meaning", "Default", "Grid"],
  [["alert_min_severity", "Gemini severity needed for an alert", 3, "1..5"],
   ["yolo_conf", "YOLO confidence threshold", 0.35, "0.15..0.65 step 0.05"],
   ["min_frames_in_zone", "frames in zone before a breach counts", 3, "1,2,3,5,8,12,20,30"],
   ["min_gemini_confidence", "Gemini self-reported confidence needed", 0.0, "0..0.95"]])
P("Objective: J = F1 (video-level) - 0.05 x (alerts raised on normal videos). The second term adds a graded cost for false alarms because F1 over 6 videos moves in huge jumps.")
tr = CD if isinstance(CD, dict) else {}
P("Result: Coordinate Descent reached J = 1.00 in 65 evaluations (2 cycles); exhaustive grid search needed 3,520 evaluations and reached the same J = 1.00, and 922 of the 3,520 grid points tie. "
  "So Coordinate Descent was about 54 times cheaper for the same answer, but the answer itself is not trustworthy (see Section 9).")
IMG("tuning_coordinate_descent.png", w=5.8, cap="Figure 5: objective versus step for Coordinate Descent.")

# ------------------------------------------------------------------ 7
H("7. Results and Evaluation")
P("Metric: video-level F1 of 'at least one alert' versus the video label. Precision and recall are reported alongside. All numbers use the same 6 videos and the whole-frame zone.")
b = R["baselines"]
T(["System", "TP", "FP", "FN", "TN", "Precision", "Recall", "F1"],
  [[k, v["TP"], v["FP"], v["FN"], v["TN"], v["precision"], v["recall"], v["F1"]] for k, v in b.items()])
P("Alerts per video at the default threshold (severity >= 3): " + ", ".join(f"{k.split('_x264')[0]} = {v}" for k, v in R["alerts_default"].items()) + ".")
P("Sensitivity to the alert threshold (other settings at default):", bold=True)
T(["alert_min_severity", "F1", "False positives", "Misses (FN)", "Alerts on normal videos"],
  [[a["sev"], a["F1"], a["FP"], a["FN"], a["false_alarm_alerts"]] for a in R["severity_ablation"]])
P("Sensitivity to the Gemini confidence filter: " + "; ".join(f'min {a["min_conf"]}: F1 {a["F1"]}' for a in R["confidence_ablation"]) + ".")
P("System speed (measured earlier on the RTX 3050): live RTSP processing about 9.6 frames per second; one Gemini call about 5 seconds; first live alert appeared about 15 seconds after the stream started.")

# ------------------------------------------------------------------ 8
H("8. Comparison with Baselines")
IMG("report/baseline_comparison.png", w=5.6, cap="Figure 6: video-level F1 for each baseline and for our system.")
B(["B0 'never alert' F1 = 0.00 and B1 'always alert' F1 = 0.80 (this is the majority-class baseline; it looks good only because 4 of 6 videos are incidents).",
   "B2 'alert on any zone breach, no VLM' F1 = 0.889: one false alarm (ShanghaiTech), no misses.",
   "Our full system at the default threshold F1 = 0.857: no false alarms, but one miss (Fighting002). Margin over B1: +0.057. Margin over B2: -0.032.",
   "So we did NOT beat the zone-breach-only baseline at the default setting on this data. The difference is one video, so it is not statistically meaningful, but it means we cannot claim that the VLM stage improved the F1 score here. What the VLM does add is: zero false alarms on the normal videos, and a written explanation with an event type for each alert, which the baselines cannot give."])

# ------------------------------------------------------------------ 9
H("9. Critical Insights and Interpretation")
B(["Why did the system miss Fighting002? It had only 3 breaches; Gemini called two of them 'intrusion' and one 'normal', all below severity 3. Our likely explanation (not proven): the trigger only fires on zone entry and has cooldowns, so the clips sent to Gemini did not show the fight itself. Gemini was never shown the decisive moment, so this points to the trigger design rather than to a Gemini error. Lowering the threshold to severity 1 or 2 'fixes' it, but for the wrong reason: the alert is for an intrusion label, not for the fight.",
   "Why is the tuned result (severity 1, F1 = 1.0) not trusted? (a) Only 6 videos, tuned and scored on the same 6; (b) the normal class produced only 4 clips in total and all were 'normal', so there is almost no test of false alarms; (c) 922 of 3,520 grid points tie, so the data cannot tell the settings apart; (d) Gemini severity 3 never occurs, so severity thresholds 3 and 4 are the same. A lower threshold would likely create many false alarms on a real, busy normal feed. We therefore kept the defaults and report the tuning as an experiment, not as an improvement.",
   "What does the confidence filter tell us? Gemini's confidence is between 0.80 and 1.00 for every clip, so it separates nothing: a filter on it either removes nothing or removes everything. With 29 clips we cannot say whether it is calibrated, so we did not rely on it as a reliability signal.",
   "Why is Coordinate Descent a good fit? The four parameters are few and the objective is cheap and piecewise-flat. A line search per parameter is simple to explain and 54 times cheaper than a full grid. Its weakness is that it can get stuck, but here grid search found nothing better, so it was not worse.",
   "Which detail matters most? The VLM adds the most value on incidents YOLO cannot see (fire in Arson001) and for suppressing harmless breaches (ShanghaiTech). It adds nothing where the trigger never fires (Fighting002).",
   "Does this support our Phase 1 expectation? Partly. The VLM correctly dismissed the only hard normal clip and gave correct, readable descriptions on Assault and Burglary, but the claim 'better than the zone-breach baseline' is not supported by 6 videos."])

# ------------------------------------------------------------------ 10
H("10. Limitations")
B(["Tiny evaluation set: 6 videos with video-level labels. Results are a demonstration, not a benchmark. The tuned parameters were selected and scored on the same data (no held-out test set).",
   "The normal class is almost empty of people; false-alarm behaviour on busy normal scenes is untested.",
   "Low-resolution footage (320x240); no Robbery or Stealing videos.",
   "Triggers fire only on zone entry: crimes outside the zone, or between people already in the zone, are missed (Fighting002).",
   "The VLM stage needs the internet and a Google API key; it can be overloaded or rate-limited (we saw 429, 503 and 504 errors) and each call takes about 5 seconds. Without internet, detection and tracking still run but no alerts are classified.",
   "A zero-shot VLM gives different answers for similar clips, and its confidence is not calibrated.",
   "Alerts are stored in a JSON file, not a database; live-stream alert times are seconds since the stream started; privacy and consent aspects of monitoring people are not addressed."])

# ------------------------------------------------------------------ 11
H("11. Conclusion and Future Scope")
P("Was the problem addressed? Yes as a working system: a person or vehicle entering a zone is detected, tracked, "
  "analysed by a VLM and shown as a described alert on a dashboard, from uploaded video or from a live RTSP camera. "
  "Was the numeric success criterion met? Against the always-alert baseline yes (0.857 vs 0.800); against the zone-breach-only baseline no (0.857 vs 0.889). "
  "We report this as it is.")
B(["Evaluate on a proper labelled set (full UCF-Crime test split with temporal annotations) with a held-out split, and measure alerts per hour on long normal footage.",
   "Add triggers that do not depend on the zone (for example sudden fast motion or crowd gathering) so fights like Fighting002 are sent to the VLM.",
   "Run a local VLM so the system works without internet and without per-call cost.",
   "Calibrate severity with a small labelled set instead of trusting the VLM's own confidence; store alerts in a database; add user accounts."])

# ------------------------------------------------------------------ 12
H("12. References")
B(["Sultani, Chen, Shah. Real-world Anomaly Detection in Surveillance Videos. CVPR 2018 (UCF-Crime).",
   "Liu et al. Future Frame Prediction for Anomaly Detection (ShanghaiTech Campus dataset). CVPR 2018.",
   "Jocher et al. Ultralytics YOLOv8. https://github.com/ultralytics/ultralytics",
   "Zhang et al. ByteTrack: Multi-Object Tracking by Associating Every Detection Box. ECCV 2022.",
   "Google. Gemini API (google-genai SDK). https://ai.google.dev",
   "FastAPI https://fastapi.tiangolo.com ; MediaMTX https://github.com/bluenviron/mediamtx",
   "Project code and README: https://github.com/Tanya-74/SmartCCTV_Project"])

out = ROOT / "report" / "Final_Project_Report.docx"
doc.save(out)
print("saved", out)
