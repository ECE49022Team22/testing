#!/usr/bin/env python3
"""Why isn't the camera seeing our stop sign? Run both detectors on the same live frames and compare.

    ~/stop-sign-eval/.venv/bin/python ~/testing/demo/tools/stop_sign_check.py --seconds 20

For every frame: the Hailo-8L YOLOv8s (the demo's detector) and YOLO26n 640 (NCNN, CPU) both run with
no confidence threshold, and the best stop-sign score of each is recorded. Also tries each frame
rotated 90/180/270 degrees with the Hailo model, in case the camera is mounted turned. Saves the frames
with the highest scores (annotated) to --out and prints a summary. Stop the demo first: it needs the camera.
"""
import argparse
import os
import sys
import time

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "testing"))
sys.path.insert(0, os.path.join(HOME, "stop-sign-eval"))
from hailo_detector import HailoDetector                  # noqa: E402  (must load before torch)
import hailo_platform                                     # noqa: E402,F401
import cv2                                                # noqa: E402
from detectors import YoloDetector                        # noqa: E402
from latest_camera import LatestFrameCamera               # noqa: E402

ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def best(dets):
    return max((d for d in dets), key=lambda d: d[4], default=None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--out", default=os.path.join(HOME, "testing/demo/logs/stop_sign_check"))
    ap.add_argument("--hailo-model", choices=("yolov8s", "yolo26n"), default="yolov8s",
                    help="model on the AI HAT+ (yolo26n needs ~/stop-sign-eval/yolo26n_hailo_model)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if a.hailo_model == "yolov8s":
        hailo = HailoDetector(conf=0.01)
    else:                                                 # the compiled YOLO26n, through Ultralytics' Hailo backend
        hailo = YoloDetector(os.path.join(HOME, "stop-sign-eval/yolo26n_hailo_model"), conf=0.01)
        hailo.close = lambda: None
    yolo26 = YoloDetector(os.path.join(HOME, "stop-sign-eval/yolo26n_640_ncnn_model"), conf=0.01, threads=2)
    cam = LatestFrameCamera(0, 640, 480, 30)
    rows, keep = [], {}
    t0 = time.time()
    try:
        while time.time() - t0 < a.seconds:
            frame, _ = cam.read()
            if frame is None:
                continue
            h, y = best(hailo(frame)), best(yolo26(frame))
            rot = {}
            for deg, code in ROT.items():
                r = best(hailo(cv2.rotate(frame, code)))
                rot[deg] = r[4] if r else 0.0
            row = {"t": time.time() - t0, "hailo": h[4] if h else 0.0, "yolo26n": y[4] if y else 0.0, **{f"hailo_rot{k}": v for k, v in rot.items()},
                   "bright": float(frame.mean())}
            rows.append(row)
            for name, det in (("hailo", h), ("yolo26n", y)):
                if det and det[4] > keep.get(name, (0,))[0]:
                    img = frame.copy()
                    x, yy, w, hh, s = det
                    cv2.rectangle(img, (x, yy), (x + w, yy + hh), (0, 0, 255), 2)
                    cv2.putText(img, f"{name} {s:.2f} ({w}x{hh}px)", (x, max(16, yy - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    keep[name] = (det[4], img, (w, hh))
            if len(rows) == 1:
                cv2.imwrite(os.path.join(a.out, "first_frame.jpg"), frame)
    finally:
        cam.release()
    for name, (s, img, size) in keep.items():
        cv2.imwrite(os.path.join(a.out, f"best_{name}.jpg"), img)

    n = len(rows)
    print(f"{n} frames in {a.seconds:.0f} s, mean brightness {sum(r['bright'] for r in rows) / max(n, 1):.0f}/255")
    for k in ("hailo", "yolo26n", "hailo_rot90", "hailo_rot180", "hailo_rot270"):
        v = sorted(r[k] for r in rows)
        if not v:
            continue
        frac = lambda thr: 100 * sum(x >= thr for x in v) / n
        print(f"  {k:13s} best {v[-1]:.2f}  median {v[n // 2]:.2f}  frames >= 0.25: {frac(0.25):4.0f}%  >= 0.6: {frac(0.6):4.0f}%")
    for name, (s, _, size) in keep.items():
        print(f"  best {name} box: {size[0]}x{size[1]} px at score {s:.2f}")
    print(f"frames saved in {a.out}")
    hailo.close()
    sys.stdout.flush()
    os._exit(0)                                           # HailoRT segfaults on implicit teardown


if __name__ == "__main__":
    main()
