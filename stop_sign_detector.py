#!/usr/bin/env python3
"""
Stop sign detector for Raspberry Pi + USB camera.

Detection pipeline (no ML model / downloads required, runs in real time on a Pi 5):
  1. Grab a frame from the USB camera (V4L2, MJPG).
  2. Convert to HSV and threshold for red (red wraps around hue 0/180,
     so two ranges are combined).
  3. Clean the mask with morphological open/close.
  4. Find external contours and keep those that look like a stop sign:
       - big enough area
       - polygon approximation has ~8 corners (octagon)
       - roughly square bounding box
       - high solidity (area / convex hull area)
  5. Require the sign to be seen for several consecutive frames before
     reporting it, to suppress one-frame false positives.

Usage:
  python3 stop_sign_detector.py                 # show live window
  python3 stop_sign_detector.py --headless      # no window (e.g. over SSH)
  python3 stop_sign_detector.py --debug         # also show the red mask
  python3 stop_sign_detector.py --device 0 --width 640 --height 480

Keys (when window is shown): q / Esc = quit, s = save snapshot
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

# HSV thresholds for red. OpenCV hue range is 0-179.
# Tune these if lighting in your environment differs.
RED_LOW_1 = np.array([0, 100, 70])
RED_HIGH_1 = np.array([10, 255, 255])
RED_LOW_2 = np.array([160, 100, 70])
RED_HIGH_2 = np.array([179, 255, 255])

MIN_AREA = 800            # px^2 at 640x480; ignore tiny red blobs
MIN_VERTICES = 7          # an octagon approximated at distance may lose/gain a corner
MAX_VERTICES = 10
MIN_ASPECT = 0.75         # bounding box w/h
MAX_ASPECT = 1.33
MIN_SOLIDITY = 0.85       # octagon is convex -> close to 1.0
APPROX_EPSILON = 0.02     # fraction of perimeter for approxPolyDP
CONFIRM_FRAMES = 3        # consecutive frames needed to confirm a detection


def open_camera(device, width, height, fps):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        sys.exit(f"ERROR: could not open camera /dev/video{device}")
    # MJPG lets the camera deliver higher resolutions/frame rates over USB
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera opened: /dev/video{device} at {actual_w}x{actual_h}")
    return cap


def red_mask(frame):
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_LOW_1, RED_HIGH_1) | cv2.inRange(hsv, RED_LOW_2, RED_HIGH_2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def detect_stop_signs(frame, min_area):
    """Return (list of detections, mask). Each detection is a dict with
    bbox (x, y, w, h), center (cx, cy), area and the approximated polygon."""
    mask = red_mask(frame)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detections = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        perimeter = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, APPROX_EPSILON * perimeter, True)
        if not (MIN_VERTICES <= len(approx) <= MAX_VERTICES):
            continue

        x, y, w, h = cv2.boundingRect(approx)
        aspect = w / float(h)
        if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
            continue

        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        solidity = area / hull_area if hull_area > 0 else 0
        if solidity < MIN_SOLIDITY:
            continue

        detections.append({
            "bbox": (x, y, w, h),
            "center": (x + w // 2, y + h // 2),
            "area": area,
            "polygon": approx,
        })

    detections.sort(key=lambda d: d["area"], reverse=True)
    return detections, mask


def draw_detections(frame, detections, confirmed):
    color = (0, 255, 0) if confirmed else (0, 255, 255)
    for d in detections:
        x, y, w, h = d["bbox"]
        cv2.drawContours(frame, [d["polygon"]], -1, color, 2)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 1)
        label = "STOP SIGN" if confirmed else "candidate"
        cv2.putText(frame, label, (x, max(y - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def on_stop_sign(detection, frame_width):
    """Hook for your robot logic (e.g. tell the planner to stop).
    Called once when a stop sign becomes confirmed."""
    x, y, w, h = detection["bbox"]
    cx, _ = detection["center"]
    offset = (cx - frame_width / 2) / (frame_width / 2)  # -1 = far left, +1 = far right
    print(f"[{time.strftime('%H:%M:%S')}] STOP SIGN detected: "
          f"size={w}x{h}px, horizontal offset={offset:+.2f}")


def main():
    parser = argparse.ArgumentParser(description="Detect stop signs from a USB camera")
    parser.add_argument("--device", type=int, default=0, help="video device index (/dev/videoN)")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--min-area", type=int, default=MIN_AREA,
                        help="minimum contour area in pixels (raise to only react to close signs)")
    parser.add_argument("--headless", action="store_true", help="don't open a display window")
    parser.add_argument("--debug", action="store_true", help="show the red mask window")
    args = parser.parse_args()

    if not args.headless and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("No display found, running headless.")
        args.headless = True

    cap = open_camera(args.device, args.width, args.height, args.fps)

    streak = 0          # consecutive frames with a candidate
    was_confirmed = False
    fps = 0.0
    last_t = time.time()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("WARNING: failed to read frame, retrying...")
                time.sleep(0.1)
                continue

            detections, mask = detect_stop_signs(frame, args.min_area)

            streak = streak + 1 if detections else 0
            confirmed = streak >= CONFIRM_FRAMES

            if confirmed and not was_confirmed:
                on_stop_sign(detections[0], frame.shape[1])
            elif was_confirmed and not confirmed:
                print(f"[{time.strftime('%H:%M:%S')}] Stop sign lost")
            was_confirmed = confirmed

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last_t, 1e-6))
            last_t = now

            if not args.headless:
                draw_detections(frame, detections, confirmed)
                cv2.putText(frame, f"{fps:.1f} FPS", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.imshow("Stop Sign Detector", frame)
                if args.debug:
                    cv2.imshow("Red mask", mask)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("s"):
                    fname = time.strftime("snapshot_%Y%m%d_%H%M%S.jpg")
                    cv2.imwrite(fname, frame)
                    print(f"Saved {fname}")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Exiting.")


if __name__ == "__main__":
    main()
