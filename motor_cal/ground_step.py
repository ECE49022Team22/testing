#!/usr/bin/env python3
"""Ground drive calibration: straight-line steps on the floor, both wheels together (the robot drives forward).

    .venv/bin/python motor_cal/ground_step.py open 20 2.5     # open loop: both wheels at 20 % duty for 2.5 s
    .venv/bin/python motor_cal/ground_step.py closed 30:2 60:2  # closed loop: 30 rpm for 2 s, then 60 rpm for 2 s

Forward = left wheel (motor 2) positive, right wheel (motor 1) negative (it's mirrored). Telemetry at 50 Hz.
Open loop: each wheel's response is fitted to a first-order-plus-dead-time model (gain rpm/%, delay, time
constant), and SIMC PI gains are suggested from it (same method as pwm-lab5/motor_autotune.py).
Closed loop: per step, rise time, overshoot, settling time, steady error and mean duty; plus the heading
drift from the gyro (straightness).

Stops (`stop`, then exits) if the LiDAR sees anything within 1.0 m ahead, if a wheel spins the wrong way or far
faster than asked, on ~/motor_cal/STOP, or on Ctrl-C. The firmware's command watchdog (400 ms) is fed by the `d`
commands sent every 50 ms in closed-loop mode; open-loop tests have their own firmware time limit.
"""
import json
import math
import os
import re
import sys
import threading
import time

import numpy as np
import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.join(os.path.dirname(HERE), "nav")]
import robot_drive as rd                     # noqa: E402
from lidar_odom import scan_to_points        # noqa: E402

TEL = re.compile(r"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+) "
                 r"tgt2=(-?[\d.]+) meas2=(-?[\d.]+) duty2=(-?[\d.]+)% cap2=(-?[\d.]+)% cnt2=(-?\d+)(.*)")
STOP_FILE = os.path.expanduser("~/motor_cal/STOP")


class Link(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.ser = serial.Serial(rd.STM32_PORT, 115200, timeout=0.1)
        self.rows, self.lock, self.alive = [], threading.Lock(), True
        self.start()

    def run(self):
        while self.alive:
            m = TEL.search(self.ser.readline().decode(errors="replace"))
            if m:
                g = [float(x) for x in m.groups()[:10]]
                # robot frame: left = motor 2, right = motor 1 with its sign flipped
                row = dict(t=time.monotonic(), tl=g[5], ml=g[6], dl=g[7], tr=-g[0], mr=-g[1], dr=-g[2], flags=m.group(11))
                with self.lock:
                    self.rows.append(row)

    def send(self, text):
        self.ser.write((text + "\n").encode())

    def stop(self):
        for _ in range(3):
            try:
                self.send("stop")
            except Exception:
                pass
            time.sleep(0.03)


def guard(link, lid, imu, wl, wr):
    """Reason to stop now, or None. wl/wr: wheel targets (rpm, robot frame) or duty signs in open loop."""
    if os.path.exists(STOP_FILE):
        return "STOP file"
    if time.monotonic() - lid.t > 0.5:
        return "LiDAR quiet"
    p = scan_to_points(lid.scan)
    if len(p):
        ahead = (p[:, 0] > 0.30) & (p[:, 0] < 1.30) & (np.abs(p[:, 1]) < 0.35)
        if ahead.any():
            return f"obstacle {p[ahead, 0].min() - 0.30:.2f} m ahead of the bumper"
    with link.lock:
        r = link.rows[-1] if link.rows else None
    if r:
        for side, meas, want in (("left", r["ml"], wl), ("right", r["mr"], wr)):
            if want > 0 and meas < -15:
                return f"{side} wheel turning backwards ({meas:+.0f} rpm)"
            if want > 0 and meas > (150 if want == 1 else 2.0 * abs(want) + 40):   # want == 1: open loop
                return f"{side} wheel far too fast ({meas:+.0f} rpm)"
        if "FAULT" in r["flags"] or "stall2" in r["flags"]:
            return "stall fault"
    return None


def fopdt(t, y):
    """First-order plus dead time fit of a step response from rest: (steady value, delay s, time constant s)."""
    ss = float(np.mean(y[t > t[-1] - 0.6]))
    if ss <= 1:
        return ss, None, None
    t10 = t[np.argmax(y >= 0.1 * ss)]
    t63 = t[np.argmax(y >= 0.632 * ss)]
    tau = max(0.02, (t63 - t10) / (1 - 0.105))           # 10 % -> 63.2 % of a first-order step = 0.895 tau
    theta = max(0.0, t63 - tau)
    return ss, theta, tau


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("open", "closed", "spin"):
        sys.exit(__doc__)
    link = Link()
    lid = rd.Lidar(); lid.start()
    imu = rd.Imu(); imu.start()
    t0 = time.monotonic()
    while (lid.scan is None or not link.rows or imu.t == 0) and time.monotonic() - t0 < 4:
        time.sleep(0.05)
    link.send("stop"); link.send("reset"); link.send("rate 50"); link.send("cap 100"); link.send("m2 cap 100")
    time.sleep(0.5)
    xs = [imu.gz for _ in range(50) if not time.sleep(0.01)]       # gyro bias, robot standing still
    imu.bias = sum(xs) / len(xs); imu.yaw = 0.0
    with link.lock:
        link.rows.clear()
    reason, t_start, steps = None, time.monotonic(), []
    try:
        if mode == "open":
            duty, secs = float(sys.argv[2]), float(sys.argv[3])
            link.send(f"open {-duty:g}"); link.send(f"m2 open {duty:g}")    # forward: right = motor 1 negative
            steps.append((time.monotonic(), duty))
            while time.monotonic() - t_start < secs:
                reason = guard(link, lid, imu, 1, 1)
                if reason:
                    break
                time.sleep(0.02)
        elif mode == "spin":                                          # spin RIGHT on the spot: left +, right -
            rpm, secs = float(sys.argv[2]), float(sys.argv[3])
            steps.append((time.monotonic(), rpm))
            gyro = []
            while time.monotonic() - t_start < secs:
                link.send(f"d {rpm:.1f} {rpm:.1f}")                         # motor 1 (right) +rpm = backward, motor 2 (left) + = forward
                gyro.append((time.monotonic(), imu.gz))
                reason = guard(link, lid, imu, 1, 1) if False else None     # spinning: the LiDAR always sees things go by
                if os.path.exists(STOP_FILE):
                    reason = "STOP file"
                if reason:
                    break
                time.sleep(0.02)
        else:
            for spec in sys.argv[2:]:
                rpm, secs = (float(x) for x in spec.split(":"))
                steps.append((time.monotonic(), rpm))
                t_step = time.monotonic()
                while time.monotonic() - t_step < secs:
                    link.send(f"d {-rpm:.1f} {rpm:.1f}")                    # robot forward at rpm
                    reason = guard(link, lid, imu, rpm, rpm)
                    if reason:
                        break
                    time.sleep(0.05)
                if reason:
                    break
    except KeyboardInterrupt:
        reason = "Ctrl-C"
    finally:
        link.stop()
    t_end = time.monotonic()
    time.sleep(1.2)                                                   # record the stop
    yaw_deg = math.degrees(imu.yaw)
    with link.lock:
        rows = list(link.rows)
    link.alive = False; imu.close()
    print(f"stopped: {reason or 'finished'}; heading change {yaw_deg:+.1f} deg (+ = turned left)")
    t = np.array([r["t"] for r in rows]) - t_start
    log = os.path.join(HERE, "ground_logs"); os.makedirs(log, exist_ok=True)
    path = os.path.join(log, f"ground_{mode}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(dict(argv=sys.argv, reason=reason, yaw_deg=yaw_deg, steps=[(s - t_start, v) for s, v in steps], rows=rows), open(path, "w"))
    print(f"log: {path} ({len(rows)} telemetry rows, {len(rows) / max(1e-3, t[-1] - t[0]):.0f} Hz)")
    run = (t >= 0) & (t <= t_end - t_start)
    if mode == "spin":
        rpm = steps[0][1]
        tt = t[run]; ml = np.array([r["ml"] for r in rows])[run]; mr = np.array([r["mr"] for r in rows])[run]
        dt = np.diff(np.concatenate(([0.0], tt)))
        circ = math.pi * 0.2032
        dl = float(np.sum(ml * dt)) / 60 * circ; dr = float(np.sum(mr * dt)) / 60 * circ       # wheel travel, m
        yaw = math.radians(-yaw_deg)                                                            # right turn = negative yaw
        g = np.array(gyro); gt = g[:, 0] - t_start; gz = -g[:, 1]                               # right turn rate, rad/s
        steady = gz[gt > gt[-1] * 0.5].mean()
        t63 = gt[np.argmax(gz >= 0.632 * steady)] if (gz >= 0.632 * steady).any() else float("nan")
        wl = np.mean(ml[tt > tt[-1] * 0.5]); wr = np.mean(mr[tt > tt[-1] * 0.5])
        track_kin = (wl - wr) / 60 * circ / steady if steady > 0.05 else float("nan")
        print(f"  turned {math.degrees(yaw):.0f} deg right; wheels travelled left {dl:+.2f} m, right {dr:+.2f} m")
        print(f"  steady turn rate {math.degrees(steady):.0f} deg/s with wheels at {wl:+.1f} / {wr:+.1f} rpm")
        print(f"  EFFECTIVE TRACK: {(dl - dr) / yaw if yaw > 0.1 else float('nan'):.3f} m (from total travel vs total turn), "
              f"{track_kin:.3f} m (from steady speeds)")
        print(f"  turning lag: 63 % of the steady turn rate {t63:.2f} s after the command")
    elif mode == "open":
        duty = steps[0][1]
        for side in ("l", "r"):
            y = np.array([r["m" + side] for r in rows])[run]; tt = t[run]
            ss, theta, tau = fopdt(tt, y)
            if theta is None:
                print(f"  {side.upper()}: didn't move ({ss:.1f} rpm)"); continue
            k = ss / duty
            tau_c = max(0.15, theta)                                   # SIMC: closed-loop time constant ~ delay
            kp = tau / (k * (tau_c + theta)); ti = min(tau, 4 * (tau_c + theta)); ki = kp / ti
            print(f"  {'left (motor 2)' if side == 'l' else 'right (motor 1)'}: {ss:5.1f} rpm at {duty:g} % -> gain {k:.2f} rpm/%, "
                  f"delay {theta * 1000:3.0f} ms, time constant {tau * 1000:3.0f} ms  ->  SIMC PI: kp {kp:.3f}, ki {ki:.3f}")
    else:
        bounds = [s - t_start for s, _ in steps] + [t_end - t_start]
        for i, (_, target) in enumerate(steps):
            a, b = bounds[i], bounds[i + 1]
            for side in ("l", "r"):
                m = (t >= a) & (t < b)
                tt, y, du = t[m] - a, np.array([r["m" + side] for r in rows])[m], np.array([r["d" + side] for r in rows])[m]
                if len(tt) < 5:
                    continue
                y0 = y[0]; span = target - y0
                rise = tt[np.argmax((y - y0) / span >= 0.9)] if span and ((y - y0) / span >= 0.9).any() else float("nan")
                peak = (y.max() - target) if span > 0 else (target - y.min())
                band = max(2.0, 0.05 * abs(target))
                outside = np.flatnonzero(np.abs(y - target) > band)
                settle = tt[outside[-1]] if len(outside) else 0.0
                tail = tt > tt[-1] - 0.5
                print(f"  step to {target:4.0f} rpm, {'left ' if side == 'l' else 'right'}: rise(90%) {rise:4.2f} s, "
                      f"overshoot {max(0.0, peak):4.1f} rpm, settled {settle:4.2f} s, steady {np.mean(y[tail]) - target:+5.1f} rpm, "
                      f"duty {np.mean(du[tail]):5.1f} %")


if __name__ == "__main__":
    main()
