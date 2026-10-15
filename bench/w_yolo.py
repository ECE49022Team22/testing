#!/usr/bin/env python3
"""USB camera -> pretrained YOLO stop-sign detector (stop-sign-eval/detectors.py), instrumented.

Camera is opened the way testing/stop_sign_detector.py does it (V4L2, MJPG, 640x480@30, buffer 1),
or with --latest through testing/latest_camera.py (background reader, always the newest frame).

Metrics
  grab_ms     time blocked waiting for a frame
  infer_ms    YOLO predict() on the 640x480 frame
  e2e_ms      frame capture timestamp (V4L2, CLOCK_MONOTONIC) -> detections ready
  age_ms      how old the frame already was when inference started
  loop_ms     one full iteration = 1 / achieved FPS
"""
import os
import sys
import time

import cv2

from common import TESTING, YOLO_DIR, Recorder, base_args, log, now

sys.path.insert(0, YOLO_DIR)
from detectors import YoloDetector  # noqa: E402


class QueuedCamera:
    """The original way: cap.read() returns whatever frame the driver has queued."""

    def __init__(self, device, width, height, fps):
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            sys.exit(f"could not open /dev/video{device}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self.size = (int(cap.get(3)), int(cap.get(4)))
        self.fps = cap.get(5)
        self.dropped = 0

    def read(self):
        ok, frame = self.cap.read()
        return (frame, self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1e3) if ok else (None, None)

    def release(self):
        self.cap.release()


def main():
    ap = base_args(__doc__)
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--weights", default=os.path.join(YOLO_DIR, "yolo26n.pt"),
                    help="a .pt file or an exported *_ncnn_model directory")
    ap.add_argument("--imgsz", type=int, default=None, help="default: the model's export size, else 640")
    ap.add_argument("--threads", type=int, default=None, help="inference threads (default: library's)")
    ap.add_argument("--latest", action="store_true", help="background reader, always the newest frame")
    ap.add_argument("--max-hz", type=float, default=0, help="cap detections per second (0 = as fast as possible)")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    rec = Recorder("yolo", a.out)

    weights = a.weights if os.path.isabs(a.weights) else os.path.join(YOLO_DIR, a.weights)
    yolo = YoloDetector(weights, conf=a.conf, imgsz=a.imgsz, threads=a.threads)
    import torch
    rec.info.update(weights=os.path.basename(weights), imgsz=yolo.imgsz, torch_threads=torch.get_num_threads(),
                    latest=a.latest, max_hz=a.max_hz, omp_wait_policy=os.environ.get("OMP_WAIT_POLICY"))

    if a.latest:
        sys.path.insert(0, TESTING)
        from latest_camera import LatestFrameCamera
        cam = LatestFrameCamera(a.device, a.width, a.height, a.fps)
    else:
        cam = QueuedCamera(a.device, a.width, a.height, a.fps)
    for _ in range(5):                      # warm up camera + model
        frame, _ = cam.read()
        if frame is not None:
            yolo(frame)
    rec.info["camera"] = f"{cam.size[0]}x{cam.size[1]}@{cam.fps:g}"
    rec.ready()

    last = last_start = None
    period = 1.0 / a.max_hz if a.max_hz else 0.0
    try:
        while not rec.stopping:
            if period and last_start is not None and now() - last_start < period:
                time.sleep(period - (now() - last_start))
            t0 = last_start = now()
            frame, ts = cam.read()
            t1 = now()
            if frame is None:
                rec.count("read_failures")
                continue
            dets = yolo(frame)
            t2 = now()
            rec.add("grab_ms", (t1 - t0) * 1e3, t1)
            rec.add("infer_ms", (t2 - t1) * 1e3, t2)
            if 0 < t2 - ts < 5:             # V4L2 timestamp is CLOCK_MONOTONIC on uvcvideo
                rec.add("e2e_ms", (t2 - ts) * 1e3, t2)
                rec.add("age_ms", (t1 - ts) * 1e3, t1)
            if last is not None:
                rec.add("loop_ms", (t2 - last) * 1e3, t2)
            last = t2
            rec.count("frames")
            if dets:
                rec.count("frames_with_stop_sign")
    finally:
        rec.counters["camera_frames_dropped"] = cam.dropped
        rec.dump()
        cam.release()


if __name__ == "__main__":
    main()
