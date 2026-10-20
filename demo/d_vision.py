#!/usr/bin/env python3
"""Demo worker: USB camera -> stop-sign detector -> annotated MJPEG stream + timing.

  --backend hailo   AI HAT+ (Hailo-8L yolov8s, conf 0.6)        <- optimized
  --backend ncnn    CPU, NCNN 640 px, 2 threads
  --backend torch   CPU, PyTorch yolo26n (the original setup)
  --camera latest   background reader, newest frame (latest_camera.py)   <- optimized
  --camera queued   plain cv2.VideoCapture.read() with 1 buffer (the original setup)

Serves http://<pi>:8091/stream.mjpg (annotated video) and publishes, every 0.5 s: FPS, capture ->
detection latency (V4L2 timestamp), inference time, frame age, and whether a stop sign is
confirmed (3 consecutive frames, like stop_sign_detector.py).
"""
import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bus import TESTING, YOLO_DIR, Pub, Window, every, install_stop, now

sys.path.insert(0, TESTING)
sys.path.insert(0, YOLO_DIR)

HEF = "/usr/share/hailo-models/yolov8s_h8l.hef"
CONFIRM_FRAMES = 3


def make_detector(backend):
    if backend == "hailo":
        from hailo_detector import HailoDetector          # must load before torch (see ROUND3_AI_HAT.md)
        return HailoDetector(HEF, conf=0.6), "AI HAT+ Hailo-8L, YOLOv8s"
    from detectors import YoloDetector
    if backend == "ncnn":
        os.environ.setdefault("OMP_WAIT_POLICY", "passive")
        return YoloDetector(os.path.join(YOLO_DIR, "yolo26n_640_ncnn_model"), conf=0.25, threads=2), "CPU, NCNN 640, 2 threads"
    return YoloDetector(os.path.join(YOLO_DIR, "yolo26n.pt"), conf=0.25), "CPU, PyTorch YOLO26n"


class QueuedCamera:
    """The original way: cv2 read() with BUFFERSIZE 1 (stale frames, 15 fps cap)."""

    def __init__(self, cv2):
        self.cv2 = cv2
        cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(3, 640), cap.set(4, 480), cap.set(5, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise RuntimeError("could not open /dev/video0")
        self.cap = cap

    def read(self):
        ok, f = self.cap.read()
        return (f, self.cap.get(self.cv2.CAP_PROP_POS_MSEC) / 1e3) if ok else (None, None)

    def release(self):
        self.cap.release()


class Stream:
    """Latest annotated JPEG, handed to any number of MJPEG clients."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg, self.seq, self.clients = None, 0, 0

    def put(self, jpeg):
        with self.cond:
            self.jpeg, self.seq = jpeg, self.seq + 1
            self.cond.notify_all()


def serve(stream, port, max_fps):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/snapshot.jpg"):
                with stream.cond:
                    jpeg = stream.jpeg
                if jpeg is None:
                    self.send_error(503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
                return
            if not self.path.startswith("/stream.mjpg"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            stream.clients += 1
            seen, last = -1, 0.0
            try:
                while True:
                    with stream.cond:
                        stream.cond.wait_for(lambda: stream.seq != seen, timeout=2)
                        jpeg, seen = stream.jpeg, stream.seq
                    if jpeg is None:
                        continue
                    wait = 1 / max_fps - (time.monotonic() - last)
                    if wait > 0:
                        time.sleep(wait)
                    last = time.monotonic()
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg))
                    self.wfile.write(jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                stream.clients -= 1

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("hailo", "ncnn", "torch"), default="hailo")
    ap.add_argument("--camera", choices=("latest", "queued"), default="latest")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--stream-fps", type=float, default=15, help="max frame rate sent to each viewer")
    a = ap.parse_args()
    stop = install_stop()
    pub = Pub("vision")
    pub.status("starting", f"loading {a.backend} detector")

    try:
        det, label = make_detector(a.backend)
    except Exception as e:
        pub.status("error", f"detector: {type(e).__name__}: {e}")
        stop.wait(5)
        return
    import cv2
    try:
        if a.camera == "latest":
            from latest_camera import LatestFrameCamera
            cam = LatestFrameCamera(0, 640, 480, 30)
        else:
            cam = QueuedCamera(cv2)
    except Exception as e:
        pub.status("disconnected", f"camera: {e}")
        stop.wait(5)
        os._exit(1)

    stream = Stream()
    serve(stream, a.port, a.stream_fps)
    e2e, infer, age = Window(0.5), Window(0.5), Window(0.5)
    st = {"frames": 0, "t0": now(), "f0": 0, "streak": 0, "confirmed": False, "best": None}

    def stats():
        t = now()
        fps = (st["frames"] - st["f0"]) / max(1e-6, t - st["t0"])
        st["t0"], st["f0"] = t, st["frames"]
        pub.send("stats", fps=round(fps, 1), e2e_ms=e2e.summary(), infer_ms=infer.summary(), age_ms=age.summary(),
                 confirmed=st["confirmed"], best=st["best"], viewers=stream.clients, backend=a.backend,
                 camera=a.camera, label=label, stream_port=a.port)

    every(0.5, stats, stop)

    # Annotating + JPEG-encoding a frame takes several ms. Doing it in the detection loop added up to
    # 60 ms to capture -> detection while someone watched, so it runs here, at most stream_fps times a
    # second, on the newest result only.
    enc, enc_cond = {"item": None}, threading.Condition()

    def encoder():
        last = 0.0
        while not stop.is_set():
            with enc_cond:
                enc_cond.wait_for(lambda: enc["item"] is not None or stop.is_set(), timeout=1)
                item, enc["item"] = enc["item"], None
            if item is None:
                continue
            wait = 1 / a.stream_fps - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
                with enc_cond:                 # something newer may have arrived while waiting
                    if enc["item"] is not None:
                        item, enc["item"] = enc["item"], None
            last = time.monotonic()
            frame, dets, confirmed = item
            img = frame.copy()
            color = (60, 60, 230) if confirmed else (0, 200, 255)
            for x, y, w, h, s in dets:
                cv2.rectangle(img, (x, y), (x + w, y + h), color, 3)
                cv2.putText(img, f"stop {s:.2f}", (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
            if confirmed:
                cv2.rectangle(img, (0, 0), (img.shape[1], 34), (40, 40, 200), -1)
                cv2.putText(img, "STOP SIGN CONFIRMED", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                stream.put(jpg.tobytes())

    threading.Thread(target=encoder, daemon=True).start()
    pub.status("ok", f"{label}; camera: {a.camera}; video on :{a.port}")
    try:
        while not stop.is_set():
            frame, ts = cam.read()
            t1 = now()
            if frame is None:
                continue
            dets = det(frame)
            t2 = now()
            infer.add((t2 - t1) * 1e3, t2)
            if ts and 0 < t2 - ts < 5:
                e2e.add((t2 - ts) * 1e3, t2)
                age.add((t1 - ts) * 1e3, t1)
            st["frames"] += 1
            st["streak"] = st["streak"] + 1 if dets else 0
            st["confirmed"] = st["streak"] >= CONFIRM_FRAMES
            st["best"] = round(max(d[4] for d in dets), 2) if dets else None
            if stream.clients:                 # hand off to the encoder thread; never encode in this loop
                with enc_cond:
                    enc["item"] = (frame, dets, st["confirmed"])
                    enc_cond.notify()
    finally:
        cam.release()
        if a.backend == "hailo":
            det.close()
        sys.stdout.flush()
        os._exit(0)                     # HailoRT segfaults on implicit teardown


if __name__ == "__main__":
    main()
