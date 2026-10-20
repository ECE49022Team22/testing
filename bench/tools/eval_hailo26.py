#!/usr/bin/env python3
"""Score YOLO26n compiled for the Hailo-8L next to the earlier models (stop-sign-eval/evaluate.py).

    cd ~/stop-sign-eval && .venv/bin/python ~/testing/bench/tools/eval_hailo26.py

Reuses results_hailo/predictions.json (PyTorch YOLO26n/YOLO11n, rules, NCNN 640/416/320, Hailo
YOLOv8s), so only the new model runs; writes results_hailo26/. The Hailo YOLOv8s isn't loaded:
two models can't hold the Hailo device at once here.
"""
import os
import shutil
import sys

import hailo_platform  # noqa: F401  load HailoRT before torch/matplotlib (see ROUND3_AI_HAT.md)

YOLO_DIR = os.path.expanduser("~/stop-sign-eval")
sys.path.insert(0, YOLO_DIR)
os.chdir(YOLO_DIR)
import evaluate  # noqa: E402
from detectors import YoloDetector  # noqa: E402

os.makedirs("results_hailo26", exist_ok=True)
shutil.copy("results_hailo/predictions.json", "results_hailo26/predictions.json")
evaluate.DETECTORS["yolo_ft4"] = ("Hailo-8L YOLOv8s", None)           # cached, never rebuilt
evaluate.SERIES_COLOR["yolo_ft4"] = "#b5651d"
DET = YoloDetector(os.path.join(YOLO_DIR, "yolo26n_hailo_model"), conf=0.05)
evaluate.DETECTORS["yolo_ft5"] = ("Hailo-8L YOLO26n", lambda: DET)
evaluate.SERIES_COLOR["yolo_ft5"] = "#6250d6"
sys.argv = ["evaluate.py", "--rescore", "--results", "results_hailo26",
            "--weights", "yolo26n_640_ncnn_model=NCNN 640", "--weights", "yolo26n_416_ncnn_model=NCNN 416",
            "--weights", "yolo26n_320_ncnn_model=NCNN 320"]
try:
    evaluate.main()
finally:
    sys.stdout.flush()
    os._exit(0)                 # skip interpreter teardown of the HailoRT objects
