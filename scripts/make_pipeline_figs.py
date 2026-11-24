"""Draws the pipeline diagram and the input/output figure used in the report. Offline.

    python scripts/make_pipeline_figs.py

Needs report/shot_input.png, shot_detect.png, shot_alert.png (crops of a real run and of the dashboard).
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "report"

# ---- pipeline diagram
fig, ax = plt.subplots(figsize=(11, 2.9))
ax.set_xlim(0, 100); ax.set_ylim(0, 30); ax.axis("off")
stages = [("Input", "video file or\nlive RTSP", "#1f3a5f"), ("YOLOv8s", "people and\nvehicles", "#2e86c1"),
          ("ByteTrack", "stable\ntrack IDs", "#2e86c1"), ("Zone trigger", "inside zone for\n3+ frames?", "#2e86c1"),
          ("Gemini VLM", "6 key frames\n-> JSON", "#c0392b"), ("Alert engine", "severity >= 3\n-> alert", "#2e86c1"),
          ("Dashboard", "live alerts\n(WebSocket)", "#1f3a5f")]
w, gap = 11.6, 2.4
for i, (a, b, c) in enumerate(stages):
    x = 1 + i * (w + gap)
    ax.add_patch(FancyBboxPatch((x, 9), w, 16, boxstyle="round,pad=0.3,rounding_size=1.2", fc=c, ec="none"))
    ax.text(x + w / 2, 20.5, a, ha="center", va="center", color="white", fontsize=10, fontweight="bold")
    ax.text(x + w / 2, 14.2, b, ha="center", va="center", color="white", fontsize=8.5)
    if i < len(stages) - 1:
        ax.annotate("", xy=(x + w + gap - 0.2, 17), xytext=(x + w + 0.2, 17), arrowprops=dict(arrowstyle="-|>", color="#444444", lw=1.5))
outs = ["frames", "boxes + class", "boxes + IDs", "breach event", "type, severity, text", "alert + snapshot", "browser"]
for i, o in enumerate(outs):
    ax.text(1 + i * (w + gap) + w / 2, 5.5, o, ha="center", va="center", fontsize=8.5, color="#2e86c1")
ax.text(50, 0.8, "Red = only stage that needs the internet. Blue = runs locally. Dark = input / output.", ha="center", fontsize=8.5, color="#444444")
fig.savefig(OUT / "pipeline_diagram.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---- input / output figure
fig, axs = plt.subplots(1, 3, figsize=(11, 3.6), gridspec_kw={"width_ratios": [1.2, 1.2, 1]})
for a, name, t in zip(axs, ["shot_input.png", "shot_detect.png", "shot_alert.png"],
                      ["(a) Input frame (Assault001, 67 s)", "(b) After YOLO + ByteTrack + zone", "(c) Output: alert on the dashboard"]):
    a.imshow(mpimg.imread(OUT / name)); a.set_title(t, fontsize=10); a.axis("off")
fig.tight_layout(); fig.savefig(OUT / "input_output.png", dpi=170); plt.close(fig)
print("saved pipeline_diagram.png, input_output.png")
