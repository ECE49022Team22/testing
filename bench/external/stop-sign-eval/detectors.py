"""Thin wrappers so both detectors take the same input and return the same output.

Every detector returns a list of detections: (x, y, w, h, score) in pixels of the
image it was given. score is the YOLO confidence, or 1.0 for the rule-based detector
(it has no notion of confidence: a blob either passes every rule or it doesn't).
"""
import os

import cv2

import stop_sign_detector as ssd   # the team's detector, copied unchanged from ECE49022Team22/testing

ROBOT_WIDTH = 640                  # the robot camera runs at 640x480


def to_robot_resolution(img, width=ROBOT_WIDTH):
    """Downscale an image so its width is 640 px, like a frame from the robot's camera."""
    h, w = img.shape[:2]
    if w == width:
        return img
    return cv2.resize(img, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)


def rules_detect(img, min_area=ssd.MIN_AREA):
    """The team's HSV-red + octagon-shape rules, single frame (no 3-frame confirmation)."""
    dets, _ = ssd.detect_stop_signs(img, min_area)
    return [(*d["bbox"], 1.0) for d in dets]


def stop_class_id(names):
    """Index of the stop-sign class: 11 ("stop sign") in the pretrained COCO models,
    0 ("stop_sign") in our fine-tuned models. Found by name so both work."""
    for i, n in (names.items() if isinstance(names, dict) else enumerate(names)):
        if "".join(ch for ch in n.lower() if ch.isalnum()) == "stopsign":
            return int(i)
    raise ValueError(f"model has no stop-sign class: {names}")


class YoloDetector:
    """Returns stop-sign boxes only (any other class, e.g. do_not_enter, is ignored)."""

    def __init__(self, weights="yolo26n.pt", conf=0.05, imgsz=None, threads=None):
        """weights: a .pt file or an exported *_ncnn_model directory (much faster on a Pi CPU).
        imgsz: None = the size an exported model was exported at, else 640.
        threads: inference threads (None = library default: 3 for PyTorch, 4 for NCNN)."""
        from ultralytics import YOLO
        self.model = YOLO(weights, task="detect")
        self.conf = conf           # keep low here; the evaluation applies the real threshold
        if imgsz is None:
            meta = os.path.join(weights, "metadata.yaml")
            if os.path.isfile(meta):
                import yaml
                with open(meta) as f:
                    imgsz = max(yaml.safe_load(f).get("imgsz", [640]))
            else:
                imgsz = 640
        self.imgsz = imgsz
        self.name = os.path.basename(os.path.normpath(weights)).rsplit(".", 1)[0]
        self.stop_id = stop_class_id(self.model.names)
        self.threads = threads
        if threads:
            import numpy as np
            import torch
            torch.set_num_threads(threads)
            self.model.predict(np.zeros((imgsz, imgsz, 3), np.uint8), imgsz=imgsz, verbose=False)
            backend = getattr(self.model.predictor.model, "backend", None)
            if getattr(backend, "net", None) is not None:
                # NCNN: the thread count lives on the net, and convolution layers fix it when the
                # model is loaded, so changing opt.num_threads afterwards does nothing for them.
                # Reload the same files into a net configured with `threads` first.
                import glob
                param = glob.glob(os.path.join(weights, "*.param"))[0]
                net = backend.pyncnn.Net()
                net.opt.use_vulkan_compute = False
                net.opt.num_threads = threads
                net.load_param(param)
                net.load_model(param[: -len(".param")] + ".bin")
                backend.net = net

    def __call__(self, img):
        r = self.model.predict(img, imgsz=self.imgsz, conf=self.conf,
                               classes=[self.stop_id], verbose=False)[0]
        out = []
        for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
            out.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1), float(c)))
        return out
