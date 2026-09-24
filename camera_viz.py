#!/usr/bin/env python3
"""
Live stop sign detection demo: shows every stage of the pipeline side by side.

  +--------------------+--------------------+
  | Camera + result    | Red mask           |
  +--------------------+--------------------+
  | Shape tests        | Numbers            |
  +--------------------+--------------------+

Camera + result  final detections (yellow = candidate, green = confirmed STOP)
Red mask         pixels that pass the HSV red threshold (white)
Shape tests      every red blob, green = passed, red = rejected + reason
Numbers          thresholds, and area / corners / aspect / solidity per blob

Sliders tune the red threshold and minimum blob size live; the defaults are the
values in stop_sign_detector.py, so copy any better values back into that file.

Usage:    .venv/bin/python camera_viz.py                 # USB camera /dev/video0
          .venv/bin/python camera_viz.py --device 1
          .venv/bin/python camera_viz.py --source stop.jpg   # still image or video file
Keys:     space = pause   s = save screenshot   r = reset sliders   q / Esc = quit
"""
import argparse
import os
import time

# Over SSH there is no DISPLAY; target the Pi's attached screen instead.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ["DISPLAY"] = ":0"

import cv2  # noqa: E402
import numpy as np

import stop_sign_detector as ssd

WINDOW = "Stop sign detector"
GREEN, YELLOW, RED, GRAY, WHITE = (0, 200, 0), (0, 220, 255), (0, 0, 255), (130, 130, 130), (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# slider name -> (default, max)
SLIDERS = {
    "Hue low (0-N)": (ssd.RED_HUE_LOW, 60),
    "Hue high (N-179)": (ssd.RED_HUE_HIGH, 179),
    "Min saturation": (ssd.RED_MIN_SAT, 255),
    "Min brightness": (ssd.RED_MIN_VAL, 255),
    "Min area": (ssd.MIN_AREA, 20000),
}


def label(img, text, org, color=WHITE, scale=0.5, thick=1, bg=(0, 0, 0)):
    """Text with a filled background so it stays readable on any image."""
    (w, h), base = cv2.getTextSize(text, FONT, scale, thick)
    x, y = org
    cv2.rectangle(img, (x - 2, y - h - 3), (x + w + 2, y + base), bg, -1)
    cv2.putText(img, text, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def title(img, text):
    label(img, text, (8, 22), WHITE, 0.6, 1, (60, 60, 60))


def open_source(args):
    if args.source:
        img = cv2.imread(args.source)
        if img is not None:
            return None, img                   # still image: reuse the same frame
        cap = cv2.VideoCapture(args.source)
        if not cap.isOpened():
            raise SystemExit(f"ERROR: could not open {args.source}")
        return cap, None
    return ssd.open_camera(args.device, args.width, args.height, args.fps), None


def draw_result(frame, blobs, confirmed, fps):
    out = frame.copy()
    for b in blobs:
        if b["reason"] is None:
            ssd.draw_detections(out, [b], confirmed)
    title(out, "Camera + result")
    label(out, f"{fps:4.1f} FPS", (out.shape[1] - 90, 22))
    if confirmed:
        label(out, "STOP SIGN", (8, out.shape[0] - 12), WHITE, 0.9, 2, GREEN)
    return out


def draw_mask(mask):
    out = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    title(out, "Red mask")
    pct = 100.0 * cv2.countNonZero(mask) / mask.size
    label(out, f"{pct:.1f}% of pixels are red", (8, out.shape[0] - 12))
    return out


def draw_shapes(frame, blobs, min_area):
    out = (frame * 0.4).astype(np.uint8)     # dim the image so outlines stand out
    for b in blobs:
        if b["area"] < min_area / 4:
            continue                         # specks: not worth drawing
        if b["reason"] == "too small":
            cv2.drawContours(out, [b["contour"]], -1, GRAY, 1)
            continue
        ok = b["reason"] is None
        color = GREEN if ok else RED
        cv2.drawContours(out, [b["contour"]], -1, color, 2)
        for px, py in b["polygon"][:, 0]:     # the simplified corners it counted
            cv2.circle(out, (int(px), int(py)), 4, YELLOW, -1)
        x, y, _, _ = b["bbox"]
        label(out, "PASS" if ok else b["reason"], (x, max(y - 6, 40)), color)
    title(out, "Shape tests")
    return out


def draw_numbers(shape, blobs, streak, confirmed, params, paused):
    out = np.full(shape, 25, np.uint8)
    title(out, "Numbers")
    y = 55

    def line(text, color=WHITE, scale=0.5):
        nonlocal y
        cv2.putText(out, text, (10, y), FONT, scale, color, 1, cv2.LINE_AA)
        y += int(26 * scale / 0.5)

    if confirmed:
        line("STOP SIGN CONFIRMED", GREEN, 0.7)
    elif streak:
        line(f"candidate ({streak}/{ssd.CONFIRM_FRAMES} frames)", YELLOW, 0.7)
    else:
        line("no stop sign", GRAY, 0.7)
    if paused:
        line("PAUSED (space to resume)", YELLOW)
    y += 6

    line(f"red: hue <= {params['hue_low']} or >= {params['hue_high']}", GRAY)
    line(f"     sat >= {params['min_sat']}, val >= {params['min_val']}", GRAY)
    line(f"pass: area >= {params['min_area']}, corners {ssd.MIN_VERTICES}-{ssd.MAX_VERTICES},", GRAY)
    line(f"      aspect {ssd.MIN_ASPECT}-{ssd.MAX_ASPECT}, solidity >= {ssd.MIN_SOLIDITY}", GRAY)
    y += 6

    line(f"{'area':>7} {'corners':>7} {'aspect':>6} {'solid':>6}  result")
    shown = [b for b in blobs if b["area"] >= params["min_area"] / 4][:6]
    for b in shown:
        ok = b["reason"] is None
        line(f"{b['area']:7.0f} {b['vertices']:7d} {b['aspect']:6.2f} {b['solidity']:6.2f}  "
             f"{'PASS' if ok else b['reason']}", GREEN if ok else RED)
    if not shown:
        line("  (no red blobs)", GRAY)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", type=int, default=0, help="camera index (/dev/videoN)")
    ap.add_argument("--source", help="image or video file instead of the camera")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--panel-width", type=int, default=480, help="width of each of the 4 panels (px)")
    args = ap.parse_args()

    cap, still = open_source(args)

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    for name, (default, maximum) in SLIDERS.items():
        cv2.createTrackbar(name, WINDOW, int(default), maximum, lambda _: None)

    streak, fps, last_t = 0, 0.0, time.time()
    paused = False
    frame = still

    while True:
        if not paused and cap is not None:
            ok, new = cap.read()
            if not ok:
                if args.source:                          # video file ended: loop it
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                print("WARNING: failed to read frame, retrying...")
                time.sleep(0.1)
                continue
            frame = new

        params = {
            "hue_low": cv2.getTrackbarPos("Hue low (0-N)", WINDOW),
            "hue_high": cv2.getTrackbarPos("Hue high (N-179)", WINDOW),
            "min_sat": cv2.getTrackbarPos("Min saturation", WINDOW),
            "min_val": cv2.getTrackbarPos("Min brightness", WINDOW),
            "min_area": max(cv2.getTrackbarPos("Min area", WINDOW), 1),
        }

        mask = ssd.red_mask(frame, params["min_sat"], params["min_val"],
                            params["hue_low"], params["hue_high"])
        blobs = ssd.analyze_contours(mask, params["min_area"])
        found = any(b["reason"] is None for b in blobs)
        if not paused:
            streak = streak + 1 if found else 0
        confirmed = streak >= ssd.CONFIRM_FRAMES

        now = time.time()
        fps = 0.9 * fps + 0.1 / max(now - last_t, 1e-6)
        last_t = now

        panels = [
            draw_result(frame, blobs, confirmed, fps),
            draw_mask(mask),
            draw_shapes(frame, blobs, params["min_area"]),
            draw_numbers(frame.shape, blobs, streak, confirmed, params, paused),
        ]
        pw = args.panel_width
        ph = int(frame.shape[0] * pw / frame.shape[1])
        panels = [cv2.resize(p, (pw, ph), interpolation=cv2.INTER_AREA) for p in panels]
        grid = np.vstack([np.hstack(panels[:2]), np.hstack(panels[2:])])
        cv2.imshow(WINDOW, grid)

        key = cv2.waitKey(1 if cap is not None else 30) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord(" "):
            paused = not paused
        elif key == ord("s"):
            fname = time.strftime("camera_viz_%Y%m%d_%H%M%S.png")
            cv2.imwrite(fname, grid)
            print(f"saved {fname}")
        elif key == ord("r"):
            for name, (default, _) in SLIDERS.items():
                cv2.setTrackbarPos(name, WINDOW, int(default))

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
