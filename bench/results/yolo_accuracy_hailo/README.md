# YOLO accuracy including the AI HAT+ (Hailo-8L YOLOv8s)

Copied from `stop-sign-eval/results_hailo/`, produced on the Pi 5 (2026-10-15) with `bench/tools/eval_hailo.py`:
the same `evaluate.py` test set as `yolo_accuracy_ncnn/`, reusing those predictions and adding
"Hailo-8L YOLOv8s" (`/usr/share/hailo-models/yolov8s_h8l.hef`, COCO "stop sign", via `testing/hailo_detector.py`).
`gallery_lookalikes_yolo_ft4.jpg` shows the red look-alikes the Hailo model calls stop signs.
In `summary.md`, `yolo_ft1-3` are NCNN 640/416/320 and `yolo_ft4` is the Hailo model.
