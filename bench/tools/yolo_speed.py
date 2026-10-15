#!/usr/bin/env python3
"""Time YoloDetector on one 640x480 photo (no camera, nothing else running).

    OMP_WAIT_POLICY=passive taskset -c 2,3 ~/stop-sign-eval/.venv/bin/python yolo_speed.py yolo26n_640_ncnn_model 2
    args: weights (.pt or *_ncnn_model, relative to ~/stop-sign-eval) [threads, 0 = library default]

Used for the PyTorch vs NCNN and thread-count numbers in ROUND2_RESULTS.md.
"""
import os
import sys
import time

import cv2

YOLO_DIR = os.path.expanduser("~/stop-sign-eval")
sys.path.insert(0, YOLO_DIR)
from detectors import YoloDetector  # noqa: E402

weights = os.path.join(YOLO_DIR, sys.argv[1] if len(sys.argv) > 1 else "yolo26n.pt")
threads = int(sys.argv[2]) if len(sys.argv) > 2 else 0
img = cv2.resize(cv2.imread(os.path.join(YOLO_DIR, "results/example_side_by_side.jpg")), (640, 480))
yolo = YoloDetector(weights, conf=0.25, threads=threads or None)
for _ in range(5):
    yolo(img)
ts = []
for _ in range(30):
    t = time.perf_counter()
    dets = yolo(img)
    ts.append((time.perf_counter() - t) * 1e3)
ts.sort()
print(f"{os.path.basename(weights)} imgsz {yolo.imgsz} threads {threads or 'default'}: "
      f"p50 {ts[15]:.1f} ms  p90 {ts[27]:.1f} ms  ({len(dets)} detections)")
