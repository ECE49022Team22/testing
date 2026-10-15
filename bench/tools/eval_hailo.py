#!/usr/bin/env python3
"""Score the Hailo-8L YOLOv8s stop-sign detector with stop-sign-eval's evaluate.py, next to the earlier models.

    cd ~/stop-sign-eval && .venv/bin/python ~/testing/bench/tools/eval_hailo.py

Reuses results_ncnn/predictions.json (PyTorch YOLO26n/YOLO11n, rules, NCNN 640/416/320), so only the
Hailo model runs; writes results_hailo/.
"""
import os
import shutil
import sys

YOLO_DIR = os.path.expanduser("~/stop-sign-eval")
sys.path.insert(0, YOLO_DIR)
sys.path.insert(0, os.path.expanduser("~/testing"))
os.chdir(YOLO_DIR)
# hailo_platform must load before evaluate (matplotlib/torch): the other order segfaults.
from hailo_detector import HailoDetector  # noqa: E402
import evaluate  # noqa: E402

os.makedirs("results_hailo", exist_ok=True)
shutil.copy("results_ncnn/predictions.json", "results_hailo/predictions.json")
# One detector for the whole run, closed explicitly: letting HailoRT's objects be garbage-collected
# (run_all drops each detector when it's done with it) segfaults.
DET = HailoDetector(conf=0.05)
evaluate.DETECTORS["yolo_ft4"] = ("Hailo-8L YOLOv8s", lambda: DET)
evaluate.SERIES_COLOR["yolo_ft4"] = "#b5651d"
sys.argv = ["evaluate.py", "--rescore", "--results", "results_hailo",
            "--weights", "yolo26n_640_ncnn_model=NCNN 640", "--weights", "yolo26n_416_ncnn_model=NCNN 416",
            "--weights", "yolo26n_320_ncnn_model=NCNN 320"]
try:
    evaluate.main()
finally:
    DET.close()
    sys.stdout.flush()
    os._exit(0)                 # skip interpreter teardown of the remaining HailoRT objects
