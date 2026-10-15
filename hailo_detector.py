"""Stop-sign detection on the AI HAT+ (Hailo-8L), same interface as stop-sign-eval's YoloDetector.

    det = HailoDetector()                 # yolov8s compiled for Hailo-8L, COCO classes
    boxes = det(frame_bgr)                # [(x, y, w, h, score), ...] in frame pixels, stop signs only
    det.close()

The HEF does the whole network *and* NMS on the chip; the CPU only letterboxes the frame to
640x640 and reads back the boxes. The model's NMS has its own score threshold built in, so `conf`
can only raise it, not lower it.
"""
import cv2
import numpy as np
from hailo_platform import (HEF, ConfigureParams, FormatType, HailoStreamInterface, InferVStreams,
                            InputVStreamParams, OutputVStreamParams, VDevice)

DEFAULT_HEF = "/usr/share/hailo-models/yolov8s_h8l.hef"
COCO_STOP_SIGN = 11


class HailoDetector:
    def __init__(self, hef=DEFAULT_HEF, conf=0.25, class_id=COCO_STOP_SIGN):
        self.conf, self.class_id = conf, class_id
        self.name = hef.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        self._hef = HEF(hef)
        self._dev = VDevice()
        params = ConfigureParams.create_from_hef(self._hef, interface=HailoStreamInterface.PCIe)
        self._ng = self._dev.configure(self._hef, params)[0]
        info = self._hef.get_input_vstream_infos()[0]
        self._in_name = info.name
        self._in_h, self._in_w = info.shape[:2]
        self._out_name = self._hef.get_output_vstream_infos()[0].name
        self._pipe = InferVStreams(self._ng, InputVStreamParams.make(self._ng, format_type=FormatType.UINT8),
                                   OutputVStreamParams.make(self._ng, format_type=FormatType.FLOAT32))
        self._pipe.__enter__()
        self._act = self._ng.activate(self._ng.create_params())
        self._act.__enter__()
        self.imgsz = self._in_w

    def _letterbox(self, img):
        h, w = img.shape[:2]
        s = min(self._in_w / w, self._in_h / h)
        nw, nh = round(w * s), round(h * s)
        canvas = np.full((self._in_h, self._in_w, 3), 114, np.uint8)
        dx, dy = (self._in_w - nw) // 2, (self._in_h - nh) // 2
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB), s, dx, dy

    def __call__(self, img):
        x, s, dx, dy = self._letterbox(img)
        out = self._pipe.infer({self._in_name: x[None]})[self._out_name][0]
        dets = np.asarray(out[self.class_id]).reshape(-1, 5)      # [ymin, xmin, ymax, xmax, score], 0-1
        boxes = []
        for y0, x0, y1, x1, score in dets.tolist():
            if score < self.conf:
                continue
            X0, Y0 = (x0 * self._in_w - dx) / s, (y0 * self._in_h - dy) / s
            X1, Y1 = (x1 * self._in_w - dx) / s, (y1 * self._in_h - dy) / s
            boxes.append((int(X0), int(Y0), int(X1 - X0), int(Y1 - Y0), float(score)))
        return boxes

    def close(self):
        self._act.__exit__(None, None, None)
        self._pipe.__exit__(None, None, None)
        self._dev.release()
