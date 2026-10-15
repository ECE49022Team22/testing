"""USB camera reader that always hands out the newest frame.

cv2.VideoCapture queues frames, so a slow consumer (YOLO at a few FPS) reads one captured during
its previous inference: in the baseline, each frame was already ~one inference old (~400 ms)
before detection started. This reads the camera continuously in a background thread and keeps
only the latest decoded frame; read() returns it as soon as there is one newer than the last.

    cam = LatestFrameCamera(0, 640, 480, 30)
    frame, ts = cam.read()      # ts = capture time, CLOCK_MONOTONIC seconds (V4L2 timestamp)
    cam.release()

Cost: every frame is MJPG-decoded even if it's never used (~3 ms each at 640x480), so lower
`fps` if the consumer can't use that many.
"""
import threading
import time

import cv2


class LatestFrameCamera:
    def __init__(self, device=0, width=640, height=480, fps=30, cpus=None):
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"could not open /dev/video{device}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        # 2, not 1: with a single V4L2 buffer the driver has nowhere to put the next frame while we
        # decode this one, so it drops every other frame (16 fps instead of 30). The reader thread
        # drains the queue continuously, so the extra buffer doesn't make frames older (34 ms either way).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        self.cap = cap
        self.size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        self._cpus = cpus
        self._cond = threading.Condition()
        self._frame, self._ts, self._seq = None, 0.0, 0
        self._taken = 0
        self.dropped = 0                 # frames replaced before anyone read them
        self.failures = 0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def _loop(self):
        if self._cpus is not None:
            import os
            os.sched_setaffinity(0, self._cpus)
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                self.failures += 1
                time.sleep(0.05)
                continue
            ts = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1e3
            with self._cond:
                if self._seq != self._taken:
                    self.dropped += 1
                self._frame, self._ts = frame, ts
                self._seq += 1
                self._cond.notify_all()

    def read(self, timeout=1.0):
        """Newest frame not returned before, and its capture time. (None, None) on timeout."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq != self._taken or not self._running, timeout):
                return None, None
            self._taken = self._seq
            return self._frame, self._ts

    def release(self):
        self._running = False
        self._thread.join(timeout=2)
        self.cap.release()
