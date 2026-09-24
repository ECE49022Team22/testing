#!/usr/bin/env python3
"""
Live BNO085 orientation viewer: 3D board model + compass heading (matplotlib animation).

Shows absolute orientation only (the fused rotation vector: gravity + magnetic north);
nothing is integrated, so there is no position/drift.

World frame is ENU as reported by the BNO085: X = East, Y = North, Z = Up.
Heading is where the board's +X axis points, clockwise from magnetic north
(add --declination to get true north). Wave the board in a figure-8 until
mag cal reads 2-3 for a trustworthy heading.

Usage:    .venv/bin/python imu_viz.py [--declination DEG]
Keys:     q = quit
"""
import argparse
import math
import os
import threading
import time

# Over SSH there is no DISPLAY and matplotlib silently falls back to the non-GUI Agg
# backend; target the Pi's attached screen instead.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ["DISPLAY"] = ":0"

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
from adafruit_bno08x import BNO_REPORT_MAGNETOMETER, BNO_REPORT_ROTATION_VECTOR
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from imu import open_imu, quat_to_euler, recover_bus

CAL_TEXT = {0: "unreliable", 1: "low", 2: "medium", 3: "high"}
CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Board as a flat box in body coordinates: 2 x 1.2 x 0.2, long side along +X.
BOX_HALF = np.array([1.0, 0.6, 0.1])
BOX_CORNERS = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * BOX_HALF
BOX_FACES = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]]
# Face order: -X, +X, -Y, +Y, bottom, top.  +X face red = "front".
BOX_COLORS = ["0.55", "#d62728", "0.7", "0.7", "0.4", "0.85"]


def quat_to_matrix(i, j, k, real):
    """Body -> world rotation matrix."""
    return np.array([
        [1 - 2 * (j * j + k * k), 2 * (i * j - k * real), 2 * (i * k + j * real)],
        [2 * (i * j + k * real), 1 - 2 * (i * i + k * k), 2 * (j * k - i * real)],
        [2 * (i * k - j * real), 2 * (j * k + i * real), 1 - 2 * (i * i + j * j)],
    ])


def heading_deg(R):
    """Compass heading of the body +X axis, clockwise from north, in [0, 360)."""
    fwd = R[:, 0]
    return math.degrees(math.atan2(fwd[0], fwd[1])) % 360   # atan2(east, north)


class ImuReader(threading.Thread):
    """Polls the IMU in the background and keeps only the newest sample.

    If no fresh rotation vector arrives for STALE_S (sensor rebooted, wire glitch, ...),
    the IMU is re-initialized; a BNO085 reset drops every enabled report.
    """

    REPORTS = (BNO_REPORT_ROTATION_VECTOR, BNO_REPORT_MAGNETOMETER)
    STALE_S = 1.0

    def __init__(self):
        super().__init__(daemon=True)
        self.bno = None
        self.lock = threading.Lock()
        self.quat = (0.0, 0.0, 0.0, 1.0)
        self.cal = 0
        self.rate = 0.0
        self.errors = 0
        self.reconnects = 0
        self.status = "connecting"

    def _connect(self):
        if self.bno is not None:
            try:
                self.bno.bus_device_obj.i2c.deinit()
            except Exception:
                pass
            self.bno = None
        with self.lock:
            self.status = "connecting"
        if recover_bus():
            print("IMU: SDA was stuck low, clocked the I2C bus free")
        try:
            self.bno = open_imu(reports=self.REPORTS, interval_us=20_000)   # 50 Hz
        except Exception as e:
            print(f"IMU init failed ({type(e).__name__}: {e}), retrying")
            time.sleep(1.0)
            return False
        with self.lock:
            self.status = "ok"
        return True

    def run(self):
        while not self._connect():
            pass
        n, t0 = 0, time.monotonic()
        last_fresh = time.monotonic()
        while True:
            if time.monotonic() - last_fresh > self.STALE_S:
                self.reconnects += 1
                print(f"IMU: no data for {self.STALE_S:.0f}s, re-initializing (#{self.reconnects})")
                while not self._connect():
                    pass
                last_fresh = time.monotonic()
                continue
            try:
                q = self.bno.quaternion
                # Drop the cached report so the next call raises until a *new* one arrives.
                self.bno._readings.pop(BNO_REPORT_ROTATION_VECTOR, None)
                # Not bno.calibration_status: that property sends an ME command to the chip on
                # every call. The accuracy field of each magnetometer report is cached here.
                cal = self.bno._magnetometer_accuracy
            except RuntimeError as e:
                if "No quaternion report" not in str(e):
                    self._log_error(e)
                time.sleep(0.005)            # no new report yet
                continue
            except Exception as e:   # the driver raises OSError, IndexError etc. on a bad packet
                self._log_error(e)
                time.sleep(0.01)
                continue
            if q == (0.0, 0.0, 0.0, 1.0):    # placeholder the chip emits around a reset
                continue
            last_fresh = time.monotonic()
            with self.lock:
                self.quat, self.cal = q, cal
            n += 1
            if time.monotonic() - t0 >= 1.0:
                self.rate, n, t0 = n / (time.monotonic() - t0), 0, time.monotonic()

    def _log_error(self, e):
        self.errors += 1
        if self.errors <= 5 or self.errors % 100 == 0:
            print(f"IMU read error #{self.errors} ({type(e).__name__}: {e})")

    def latest(self):
        with self.lock:
            return self.quat, self.cal, self.rate, self.status


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--declination", type=float, default=0.0,
                    help="magnetic declination in degrees (east positive) to show true heading")
    args = ap.parse_args()

    reader = ImuReader()
    reader.start()

    fig = plt.figure(figsize=(13, 6.5))
    fig.canvas.manager.set_window_title("BNO085 orientation")
    ax3d = fig.add_subplot(1, 2, 1, projection="3d")
    axc = fig.add_subplot(1, 2, 2, projection="polar")

    # --- 3D view (ENU) ---
    lim = 1.6
    ax3d.set_xlim(-lim, lim)
    ax3d.set_ylim(-lim, lim)
    ax3d.set_zlim(-lim, lim)
    ax3d.set_box_aspect((1, 1, 1))
    ax3d.set_xlabel("East")
    ax3d.set_ylabel("North")
    ax3d.set_zlabel("Up")
    ax3d.set_xticklabels([])
    ax3d.set_yticklabels([])
    ax3d.set_zticklabels([])
    ax3d.view_init(elev=25, azim=-60)
    ax3d.plot([0, 0], [0, lim], [-lim, -lim], color="k", lw=1)   # north pointer on the floor
    ax3d.text(0, lim * 1.05, -lim, "N", fontsize=14, weight="bold")

    box = Poly3DCollection([], facecolors=BOX_COLORS, edgecolors="k", linewidths=0.8, alpha=0.6)
    ax3d.add_collection3d(box)
    axis_lines = [ax3d.plot([], [], [], color=c, lw=3, label=f"body {n}")[0]
                  for c, n in (("#d62728", "+X (heading)"), ("#2ca02c", "+Y"), ("#1f77b4", "+Z"))]
    ax3d.legend(loc="upper left", fontsize=9)

    # --- compass ---
    axc.set_theta_zero_location("N")
    axc.set_theta_direction(-1)          # clockwise, like a compass
    axc.set_rlim(0, 1)
    axc.set_yticklabels([])
    axc.set_xticks(np.radians(np.arange(0, 360, 45)))
    axc.set_xticklabels(CARDINALS, fontsize=13, weight="bold")
    (needle,) = axc.plot([0, 0], [0, 0.9], color="#d62728", lw=4, solid_capstyle="round")
    (tail,) = axc.plot([0, 0], [0, 0.35], color="0.4", lw=4, solid_capstyle="round")
    heading_text = axc.text(0, 0, "", transform=axc.transAxes, ha="center", va="center")
    heading_text.set_position((0.5, -0.12))
    heading_text.set_fontsize(22)
    info_text = fig.text(0.5, 0.02, "", ha="center", family="monospace", fontsize=11)

    def update(_frame):
        q, cal, rate, status = reader.latest()
        R = quat_to_matrix(*q)

        pts = BOX_CORNERS @ R.T
        box.set_verts([pts[f] for f in BOX_FACES])
        for idx, line in enumerate(axis_lines):
            tip = R[:, idx] * 1.55
            line.set_data_3d([0, tip[0]], [0, tip[1]], [0, tip[2]])

        hdg = (heading_deg(R) + args.declination) % 360
        th = math.radians(hdg)
        needle.set_xdata([th, th])
        tail.set_xdata([th + math.pi, th + math.pi])
        cardinal = CARDINALS[int((hdg + 22.5) // 45) % 8]
        heading_text.set_text(f"{hdg:5.1f}°  {cardinal}")
        heading_text.set_color("k" if cal >= 2 else "#d62728")

        roll, pitch, _ = quat_to_euler(*q)
        if status != "ok":
            info_text.set_text(f"IMU {status}...  (reconnects: {reader.reconnects})")
            info_text.set_color("#d62728")
            return [box, *axis_lines, needle, tail, heading_text, info_text]
        info_text.set_color("k")
        info_text.set_text(f"roll {roll:6.1f}°   pitch {pitch:6.1f}°   heading {hdg:5.1f}°   "
                           f"mag cal {cal} ({CAL_TEXT.get(cal, '?')})   {rate:4.0f} Hz   "
                           f"reconnects {reader.reconnects}"
                           + ("" if cal >= 2 else "   <- wave in a figure-8 to calibrate"))
        return [box, *axis_lines, needle, tail, heading_text, info_text]

    fig.canvas.mpl_connect("key_press_event", lambda e: plt.close(fig) if e.key == "q" else None)
    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)  # noqa: F841 (keep ref)
    plt.show()


if __name__ == "__main__":
    main()
