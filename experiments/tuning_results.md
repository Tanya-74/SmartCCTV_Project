### Parameters and scores

| Parameter             | Default | Tuned (CD) | Grid-search best |
|-----------------------|---------|------------|------------------|
| alert_min_severity    | 3       | 1          | 1                |
| yolo_conf             | 0.35    | 0.35       | 0.15             |
| min_frames_in_zone    | 3       | 3          | 1                |
| min_gemini_confidence | 0.0     | 0.0        | 0.0              |
| F1 (video level)      | 0.857   | 1.000      | 1.000            |
| false-alarm alerts    | 0       | 0          | 0                |
| objective J           | 0.857   | 1.000      | 1.000            |
| TP / FP / FN / TN     | 3/0/1/2 | 4/0/0/2    | 4/0/0/2          |

### Alerts per video

| Video                  | Truth    | Alerts @ default | Alerts @ tuned |
|------------------------|----------|------------------|----------------|
| Arson001_x264          | incident | 2                | 7              |
| Assault001_x264        | incident | 6                | 8              |
| Burglary001_x264       | incident | 6                | 6              |
| Fighting002_x264       | incident | 0                | 2              |
| Normal_Videos_003_x264 | normal   | 0                | 0              |
| shanghaitech_01_0014   | normal   | 0                | 0              |

### Cost

```
Coordinate Descent: 65 objective evaluations (2 cycles x 32), 0.13s, best J = 1.0000
Grid search:        3520 objective evaluations, 0.60s, best J = 1.0000; 922 grid point(s) tie at that value
```
