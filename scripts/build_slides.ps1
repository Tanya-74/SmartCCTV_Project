# Builds report/Final_Presentation.pptx using the installed PowerPoint. Run: powershell -File scripts\build_slides.ps1
$root = Split-Path -Parent $PSScriptRoot
$out  = Join-Path $root "report\Final_Presentation.pptx"
$r = Get-Content (Join-Path $root "report\results.json") -Raw | ConvertFrom-Json

$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Add(0)
$pres.PageSetup.SlideWidth = 960; $pres.PageSetup.SlideHeight = 540
function RGBc($r,$g,$b){ return $r + 256*$g + 65536*$b }
$NAVY = RGBc 22 42 74; $INK = RGBc 34 40 49; $GREY = RGBc 110 120 135; $ACC = RGBc 30 132 73; $RED = RGBc 192 57 43; $PALE = RGBc 240 244 249

function NewSlide($title){
  $s = $pres.Slides.Add($pres.Slides.Count + 1, 12)
  $bar = $s.Shapes.AddShape(1, 0, 0, 960, 78); $bar.Fill.ForeColor.RGB = $NAVY; $bar.Line.Visible = 0
  $t = $s.Shapes.AddTextbox(1, 36, 14, 890, 52); $t.TextFrame.TextRange.Text = $title
  $t.TextFrame.TextRange.Font.Size = 30; $t.TextFrame.TextRange.Font.Bold = 1; $t.TextFrame.TextRange.Font.Name = "Calibri"
  $t.TextFrame.TextRange.Font.Color.RGB = RGBc 255 255 255; $t.TextFrame.VerticalAnchor = 3
  $n = $s.Shapes.AddTextbox(1, 880, 508, 60, 22); $n.TextFrame.TextRange.Text = "$($pres.Slides.Count)"
  $n.TextFrame.TextRange.Font.Size = 12; $n.TextFrame.TextRange.Font.Color.RGB = $GREY; $n.TextFrame.TextRange.ParagraphFormat.Alignment = 3
  return $s
}
function Bullets($s, $items, $x=40, $y=100, $w=880, $h=390, $size=22){
  $b = $s.Shapes.AddTextbox(1, $x, $y, $w, $h); $b.TextFrame.WordWrap = -1
  $b.TextFrame.TextRange.Text = ($items -join "`r")
  $tr = $b.TextFrame.TextRange; $tr.Font.Size = $size; $tr.Font.Name = "Calibri"; $tr.Font.Color.RGB = $INK
  $tr.ParagraphFormat.Bullet.Visible = -1; $tr.ParagraphFormat.Bullet.Character = 8226
  $tr.ParagraphFormat.SpaceAfter = 9
  $b.TextFrame.Ruler.Levels(1).FirstMargin = 0; $b.TextFrame.Ruler.Levels(1).LeftMargin = 20
  return $b
}
function Pic($s, $rel, $x, $y, $w){ $p = $s.Shapes.AddPicture((Join-Path $root $rel), 0, -1, $x, $y, $w, -1); return $p }
function Note($s, $text){ $s.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = $text }
function Table($s, $rows, $x, $y, $w, $colw, $size=16){
  $nr = $rows.Count; $nc = $rows[0].Count
  $sh = $s.Shapes.AddTable($nr, $nc, $x, $y, $w, 30 * $nr); $t = $sh.Table
  for($i=0;$i -lt $nr;$i++){ for($j=0;$j -lt $nc;$j++){
      $c = $t.Cell($i+1,$j+1); $c.Shape.TextFrame.TextRange.Text = [string]$rows[$i][$j]
      $c.Shape.TextFrame.TextRange.Font.Size = $size; $c.Shape.TextFrame.TextRange.Font.Name = "Calibri"
      if($i -eq 0){ $c.Shape.Fill.ForeColor.RGB = $NAVY; $c.Shape.TextFrame.TextRange.Font.Color.RGB = RGBc 255 255 255; $c.Shape.TextFrame.TextRange.Font.Bold = 1 }
      else { $c.Shape.Fill.ForeColor.RGB = $(if($i % 2){ $PALE } else { RGBc 255 255 255 }); $c.Shape.TextFrame.TextRange.Font.Color.RGB = $INK } } }
  for($j=0;$j -lt $nc;$j++){ $t.Columns($j+1).Width = $colw[$j] }
  return $sh
}

# 1 ---- title
$s = $pres.Slides.Add(1, 12)
$bg = $s.Shapes.AddShape(1, 0, 0, 960, 540); $bg.Fill.ForeColor.RGB = $NAVY; $bg.Line.Visible = 0
$t = $s.Shapes.AddTextbox(1, 60, 150, 840, 140); $t.TextFrame.WordWrap = -1
$t.TextFrame.TextRange.Text = "Smart CCTV`rReal-Time Perimeter Intrusion and Crime Detection using a Vision-Language Model"
$t.TextFrame.TextRange.Font.Color.RGB = RGBc 255 255 255; $t.TextFrame.TextRange.Font.Name = "Calibri"
$t.TextFrame.TextRange.Paragraphs(1).Font.Size = 54; $t.TextFrame.TextRange.Paragraphs(1).Font.Bold = 1
$t.TextFrame.TextRange.Paragraphs(2).Font.Size = 26
$u = $s.Shapes.AddTextbox(1, 60, 400, 840, 80)
$u.TextFrame.TextRange.Text = "Machine Learning Project - Phase 2 Final Evaluation`rNIIT University - 25 November 2026`rTeam: ____________________"
$u.TextFrame.TextRange.Font.Size = 18; $u.TextFrame.TextRange.Font.Color.RGB = RGBc 200 212 230
Note $s "Say your names, then one sentence: our system watches a camera, and only raises an alert when a person or vehicle enters a restricted zone AND an AI model says the clip looks like a real incident."

# 2 ---- problem
$s = NewSlide "The problem"
Bullets $s @("A guard cannot watch many camera feeds all day.",
 "A simple 'motion detected' alarm fires constantly, so people stop trusting it.",
 "We want an alert only when the footage looks like a real incident - with a one-line explanation of what happened.",
 "Input: a 6-second clip around the moment someone enters a restricted zone.",
 "Output: event type + severity 1-5 + description. Alert if severity >= 3.",
 "Success: video-level F1 of 'alert / no alert', compared with simple baselines.") | Out-Null
Note $s "Phase 1 specification statement is in the report, section 1. Be ready to say what one sample is: a breach moment, and its 6-second clip."

# 3 ---- pipeline
$s = NewSlide "How the system works"
$steps = @("Video / live RTSP camera","YOLOv8s`ndetect people, vehicles","ByteTrack`nstable ID per object","Zone trigger`nenters restricted zone","Gemini VLM`n6 key frames -> JSON","Alert engine`nseverity >= 3","Live dashboard")
for($i=0;$i -lt $steps.Count;$i++){
  $bx = $s.Shapes.AddShape(5, 24 + $i*132, 170, 118, 110); $bx.Fill.ForeColor.RGB = $(if($i -eq 4){ $ACC } else { $NAVY }); $bx.Line.Visible = 0
  $bx.TextFrame.TextRange.Text = $steps[$i]; $bx.TextFrame.TextRange.Font.Size = 14; $bx.TextFrame.TextRange.Font.Color.RGB = RGBc 255 255 255; $bx.TextFrame.WordWrap = -1
  if($i -lt $steps.Count-1){ $a = $s.Shapes.AddTextbox(1, 24 + $i*132 + 116, 205, 20, 30); $a.TextFrame.TextRange.Text = ">"; $a.TextFrame.TextRange.Font.Size = 22; $a.TextFrame.TextRange.Font.Color.RGB = $GREY } }
Bullets $s @("Only breach moments go to Gemini - this saves cost and time (one call is about 5 s).",
 "No model is trained by us: YOLO and Gemini are pretrained. Our ML work is the decision layer and its evaluation.",
 "Runs on a laptop GPU (RTX 3050); live camera processed at about 9.6 frames per second.") $40 320 880 180 20 | Out-Null
Note $s "Explain why a VLM: a box detector can see 'a person', but not 'a fire' or 'a fight'. Gemini describes the action."

# 4 ---- dataset
$s = NewSlide "Dataset"
$rows = @(,@("Video","Label","Frames","Size","Breaches"))
foreach($v in $r.videos){ $rows += ,@(($v.video -replace "_x264",""), $v.label, $v.frames, "$($v.width)x$($v.height)", $v.breaches) }
Table $s $rows 40 100 880 @(330,130,120,150,150) 18 | Out-Null
Bullets $s @("UCF-Crime sample + ShanghaiTech clip (via Kaggle). 6 videos, about 16,300 frames: 4 incident, 2 normal.",
 "Labels are per video, taken from the dataset's file names - they do not say when the incident happens.",
 "Small and low-resolution (320x240). No Robbery or Stealing videos were available.") 40 340 880 160 18 | Out-Null
Note $s "Be upfront: this is a demonstration set, not a benchmark. Labels are video-level."

# 5 ---- EDA (breaches)
$s = NewSlide "What the data looks like (1/2): breaches and alerts"
Pic $s "report\eda_breaches_alerts.png" 30 100 600 | Out-Null
Bullets $s @("Normal video has 0 breaches: it is nearly empty (2 person boxes in 2,822 frames).",
 "Only one normal clip (ShanghaiTech) was a real test for false alarms.",
 "Arson: 6,623 vehicle boxes, few people - the fire itself is invisible to YOLO.") 650 100 290 400 17 | Out-Null
Note $s "Insight: the 'normal' class has almost no hard negatives."

# 5b ---- EDA (Gemini)
$s = NewSlide "What the data looks like (2/2): what Gemini said"
Pic $s "report\eda_gemini_outputs.png" 30 100 600 | Out-Null
Bullets $s @("29 breach clips were judged at default settings.",
 "Gemini never gave severity 3, so thresholds 3 and 4 behave the same.",
 "Its confidence is always 0.80-1.00, so it separates nothing and is not a useful filter.") 650 100 290 400 17 | Out-Null
Note $s "Insight: Gemini's confidence is always high, so it is not useful as a filter."

# 6 ---- tuning
$s = NewSlide "Tuning the alert rule: Coordinate Descent"
Bullets $s @("4 parameters: alert severity, YOLO confidence, frames in zone, Gemini confidence.",
 "Coordinate Descent: improve ONE parameter at a time, keep the best value, repeat until nothing improves.",
 "Objective: F1 minus 0.05 per false alarm. Gemini answers cached, so tuning runs offline in under a second.",
 "65 evaluations vs 3,520 for grid search - both reach the same best score.") 40 100 430 400 18 | Out-Null
$pc = Pic $s "tuning_coordinate_descent.png" 510 95 400
$w = $s.Shapes.AddTextbox(1, 485, ($pc.Top + $pc.Height + 4), 450, 70); $w.TextFrame.WordWrap = -1
$w.TextFrame.TextRange.Text = "Tuned answer (severity >= 1, F1 = 1.0) is NOT adopted: 6 videos only, tuned and scored on the same data, and 922 settings tie."
$w.TextFrame.TextRange.Font.Size = 16; $w.TextFrame.TextRange.Font.Color.RGB = $RED; $w.TextFrame.TextRange.Font.Bold = 1
Note $s "Why Coordinate Descent: few parameters, cheap objective, easy to explain. Be honest that the tuned result is not trustworthy; we kept the defaults."

# 7 ---- results
$s = NewSlide "Results (video-level, 6 videos)"
$rows = @(,@("System","TP","FP","FN","TN","Precision","Recall","F1"))
foreach($p in $r.baselines.PSObject.Properties){ $v = $p.Value; $rows += ,@(($p.Name -replace "Ours: YOLO\+track\+zone\+Gemini \(defaults\)","Ours (default settings)"), $v.TP, $v.FP, $v.FN, $v.TN, $v.precision, $v.recall, $v.F1) }
Table $s $rows 30 100 900 @(400,50,50,50,50,100,100,100) 16 | Out-Null
Bullets $s @("Default system: no false alarms, one miss (Fighting002). F1 = 0.857.",
 "Always-alert baseline F1 = 0.80; zone-breach-only baseline F1 = 0.889.",
 "Alerts at default: Arson 2, Assault 6, Burglary 6, Fighting 0, both normal videos 0.") 40 330 880 160 20 | Out-Null
Note $s "Read the table out loud. The default system is +0.057 over always-alert and -0.032 below breach-only. That difference is one video."

# 8 ---- baselines
$s = NewSlide "Comparison with baselines - honest reading"
Pic $s "report\baseline_comparison.png" 30 95 520 | Out-Null
Bullets $s @("We beat the always-alert baseline (0.857 vs 0.800).",
 "We did NOT beat zone-breach-only (0.857 vs 0.889). The gap is a single video, so it is not significant.",
 "What the VLM adds: zero false alarms on normal videos, and a written explanation for every alert.",
 "The 1.00 bar is the tuned setting we do not trust.") 570 100 360 400 18 | Out-Null
Note $s "If asked: does the VLM help? On this data, the F1 does not show it. The value is in explanations and fewer false alarms, but 6 videos cannot prove it."

# 9 ---- insights
$s = NewSlide "Critical insights"
Bullets $s @("Fighting002 was missed: the trigger only fires on zone entry, so Gemini was probably never shown the fight itself. Trigger design, not Gemini.",
 "Lowering the threshold 'fixes' it, but only because Gemini calls it an intrusion - right score, wrong reason.",
 "Gemini's confidence is always 0.80-1.00: it cannot be used to filter alerts.",
 "The VLM is most useful where YOLO is blind (fire in Arson) and for dismissing harmless breaches (ShanghaiTech).",
 "A higher score is not a better project here: we chose to keep the defaults and explain why.") 40 100 880 400 21 | Out-Null
Note $s "This is the 'interpretation' slide - rubric 4. Explain why, not just what."

# 10 ---- limitations
$s = NewSlide "Limitations"
Bullets $s @("Tiny test set (6 videos), video-level labels, no held-out split.",
 "Quiet normal class: false alarms on busy normal scenes are untested.",
 "Low-resolution footage; zone-entry trigger misses fights between people already inside.",
 "Needs internet and an API key for classification; Gemini can be overloaded (429/503/504 seen); about 5 s per call.",
 "Without internet: detection and tracking still run, but no alerts are classified.",
 "Alerts stored in a JSON file; no database, no privacy or consent handling.") 40 100 880 400 21 | Out-Null
Note $s "Say the internet point clearly. If the interviewer asks to turn off wifi: detection still works, Gemini classification does not."

# 11 ---- conclusion
$s = NewSlide "Conclusion and future work"
Bullets $s @("Built a working end-to-end system: upload or live RTSP camera -> detect -> track -> VLM -> alert dashboard.",
 "Success criterion: met against always-alert, not met against zone-breach-only. Reported as measured.",
 "Next: evaluate on the full UCF-Crime test set with a proper split; add triggers that do not depend on the zone.",
 "Next: a local VLM so it works offline; use a small labelled set to calibrate severity; store alerts in a database.") 40 100 880 400 22 | Out-Null
Note $s "Close with the honest statement of the result, then go to the live demo."

# 12 ---- demo
$s = NewSlide "Live demo"
Bullets $s @("1. Start the server and open the dashboard.",
 "2. Upload Assault001 -> alerts appear with event type, severity and description.",
 "3. Upload the normal video -> no alerts.",
 "4. Live mode: fake RTSP camera (MediaMTX + ffmpeg) -> alerts from a live stream.",
 "Backup: previously generated alerts stay on the dashboard if Gemini or the internet fails.") 40 100 880 400 22 | Out-Null
Note $s "See DEMO_CHECKLIST.md. Do a full dry run beforehand with the internet on, so the dashboard already holds alerts."

$tmp = Join-Path $env:TEMP "smartcctv_deck.pptx"
if(Test-Path $tmp){ Remove-Item $tmp -Force }
$pres.SaveAs($tmp); $pres.Close(); $app.Quit()
Copy-Item $tmp $out -Force
"saved $out"
