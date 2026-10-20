# YOLO accuracy including YOLO26n compiled for the AI HAT+ (Hailo-8L)

Copied from `stop-sign-eval/results_hailo26/`, produced on the Pi (2026-10-20) with `bench/tools/eval_hailo26.py`:
the same `evaluate.py` test set as `yolo_accuracy_ncnn/` and `yolo_accuracy_hailo/`, adding
"Hailo-8L YOLO26n" (`~/stop-sign-eval/yolo26n_hailo_model`, compiled on an x86 PC from the kit made by
`stop-sign-eval/hailo/make_kit.py`: DFC for hailo8l, Ultralytics 8.4.174, 1,047 calibration images).
In `summary.md`, `yolo_ft1-3` are NCNN 640/416/320, `yolo_ft4` the Hailo YOLOv8s and `yolo_ft5` the Hailo YOLO26n.

Result: after INT8 compilation YOLO26n finds fewer signs than the Hailo YOLOv8s (95% vs 99% of real photos;
smallest reliable sign 40 px vs 24 px; 30% vs 75% of small occluded signs) but has fewer false alarms
(1% vs 8% at conf 0.25; "no entry" discs 42% vs 57% at conf >= 0.5), at 34 vs 17 ms per frame.
