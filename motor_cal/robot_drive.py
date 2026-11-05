#!/usr/bin/env python3
"""Floor driving tests for the two-wheel robot, with a LiDAR crash guard.

  robot_drive.py probe            creep forward ~25 cm: which LiDAR angle is the robot's front
  robot_drive.py spin             spin in place ~1 turn: effective track width from gyro vs wheels
  robot_drive.py circle --diameter 2 [--side left|right] [--speed 0.25] [--laps 1]

Wheels: 8 in (0.2032 m) diameter. Left = STM32 motor 2 (+ rolls the robot forward), right = motor 1
(+ rolls it backward), so wheel targets in the robot's frame are sent as "d <-right> <left>". (Checked
on the floor 2026-11-04: speeding up motor 1 turned the robot left, gyro and eyes agreeing.)

Safety: stops (target 0 on both wheels) if the LiDAR sees anything closer than --stop-dist beyond the
robot's own chassis returns (< SELF_MM), if the LiDAR or IMU goes quiet, if a motor faults, if
~/motor_cal/STOP exists, or after --max-s. The STM32 holds its last target forever, so this script
must be the one to stop: it sends "stop" on every exit path it can.
"""
import argparse
import json
import math
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.expanduser("~/testing"))
import serial                                     # noqa: E402

WHEEL_D = 0.2032                                  # m (8 in)
WHEEL_C = math.pi * WHEEL_D                       # m per wheel turn
RIGHT_SIGN, LEFT_SIGN = -1, 1                     # right wheel = motor 1, left wheel = motor 2
SELF_MM = 150                                     # LiDAR returns closer than this are the robot itself
STOP_FILE = os.path.expanduser("~/motor_cal/STOP")
CAL_FILE = os.path.expanduser("~/motor_cal/robot_geometry.json")
TEL = re.compile(r"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+) "
                 r"tgt2=(-?[\d.]+) meas2=(-?[\d.]+) duty2=(-?[\d.]+)% cap2=(-?[\d.]+)% cnt2=(-?\d+)(.*)")
COUNTS_PER_REV = 751.8


def rpm_for(v):
    """Wheel RPM for a ground speed in m/s."""
    return v / WHEEL_C * 60.0


class Lidar(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        import lidar
        self.dev = lidar.STL27L("/dev/ttyAMA2")
        self.scan, self.t = None, 0.0
        self.odom = None                          # LidarOdom, when odometry is on
        self.path = []                            # (t, x, y, heading, ok) per scan, robot start frame

    def start_odometry(self):
        from lidar_odom import LidarOdom
        self.path = []
        self.odom = LidarOdom()

    def run(self):
        for s in self.dev.scans():
            self.scan, self.t = s, time.monotonic()
            if self.odom is not None:
                try:
                    (x, y, th), ok = self.odom.update(s)
                    self.path.append((self.t, x, y, th, ok))
                except Exception as e:            # odometry must never stop the scans (the guard needs them)
                    print(f"odometry error: {e!r}", flush=True)

    def speed(self, window=0.6):
        """True ground speed (m/s) over the last `window` s from scan matching, or None."""
        p = self.path
        if len(p) < 3 or time.monotonic() - p[-1][0] > 0.4:
            return None
        old = next((q for q in reversed(p) if p[-1][0] - q[0] >= window), None)
        if old is None:
            return None
        return math.hypot(p[-1][1] - old[1], p[-1][2] - old[2]) / (p[-1][0] - old[0])

    def nearest(self, ignore_mm=SELF_MM):
        """(distance mm, angle deg) of the nearest return that isn't the robot itself."""
        best = (1e9, None)
        for a, d, _ in self.scan or ():
            if d >= ignore_mm and d < best[0]:
                best = (d, a)
        return best

    def per_degree(self):
        out = [1e9] * 360
        for a, d, _ in self.scan or ():
            if d >= SELF_MM:
                i = int(a) % 360
                out[i] = min(out[i], d)
        return out


class Imu(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        import imu
        from adafruit_bno08x import BNO_REPORT_GYROSCOPE
        self.imu, self.GYRO = imu, BNO_REPORT_GYROSCOPE
        self.bno = imu.open_imu(reports=(BNO_REPORT_GYROSCOPE,), interval_us=10_000)
        self.gz, self.yaw, self.t = 0.0, 0.0, 0.0
        self.bias = 0.0
        self.stop = threading.Event()

    def run(self):
        last = None
        while not self.stop.is_set():
            if not self.imu.wait_sample(self.bno, 0.2):
                continue
            g = self.bno._readings.pop(self.GYRO, None)
            if g is None:
                continue
            now = time.monotonic()
            self.gz = g[2] - self.bias
            if last is not None:
                self.yaw += self.gz * (now - last)
            last, self.t = now, now

    def close(self):
        self.stop.set()
        time.sleep(0.3)
        self.imu.close_imu(self.bno)


class Stm32:
    def __init__(self, port="/dev/ttyUSB0"):
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        self.row, self.t, self.flags = None, 0.0, ""
        self.replies = []                         # OK/ERR lines, newest last
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        self.ser.write(b"reset\nrate 20\n")

    def _reader(self):
        while self.alive:
            try:
                line = self.ser.readline().decode(errors="replace").strip()
            except Exception:
                continue
            if line.startswith(("OK", "ERR")):
                self.replies.append(line)
            m = TEL.match(line)
            if m:
                g = [float(x) for x in m.groups()[:10]]
                self.row, self.flags, self.t = g, m.group(11), time.monotonic()

    def wheels(self):
        """(left, right) measured wheel RPM and encoder counts, robot frame."""
        g = self.row
        return (g[6] * LEFT_SIGN, g[1] * RIGHT_SIGN), (g[9] * LEFT_SIGN, g[4] * RIGHT_SIGN)

    def drive(self, left_rpm, right_rpm):
        self.ser.write(f"d {right_rpm * RIGHT_SIGN + 0.0:.1f} {left_rpm * LEFT_SIGN + 0.0:.1f}\n".encode())

    def command(self, text, timeout=1.0):
        """Send a command and return its OK/ERR reply (or None)."""
        n = len(self.replies)
        self.ser.write((text + "\n").encode())
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if len(self.replies) > n:
                return self.replies[n]
            time.sleep(0.01)
        return None

    def gains(self, prefix=""):
        """Current gains of motor 1 ("") or motor 2 ("m2 ") as a dict, read by re-sending its kd."""
        r = self.command(f"{prefix}kd 0") or ""
        return {k: float(v) for k, v in re.findall(r"(k[pidfs])=(-?[\d.]+)", r)}

    def stop(self):
        for _ in range(3):
            try:
                self.ser.write(b"stop\n")
            except Exception:
                pass
            time.sleep(0.05)

    def close(self):
        self.stop()
        self.ser.write(b"rate 10\n")
        time.sleep(0.1)
        self.alive = False
        self.ser.close()


class Guard:
    """Reasons to stop right now, or None."""

    def __init__(self, lid, imu, mcu, stop_mm, max_s):
        self.lid, self.imu, self.mcu, self.stop_mm = lid, imu, mcu, stop_mm
        self.deadline = time.monotonic() + max_s

    def check(self):
        now = time.monotonic()
        if os.path.exists(STOP_FILE):
            return "STOP file present"
        if now > self.deadline:
            return "time limit"
        if now - self.lid.t > 0.5:
            return "LiDAR quiet for 0.5 s"
        if self.imu and now - self.imu.t > 0.3:
            return "IMU quiet for 0.3 s"
        if now - self.mcu.t > 0.5:
            return "no STM32 telemetry for 0.5 s"
        if "FAULT" in self.mcu.flags or "stall2" in self.mcu.flags:
            return "motor stall fault"
        d, a = self.lid.nearest()
        if d < self.stop_mm:
            return f"obstacle {d} mm at {a:.0f} deg"
        return None


def start(args, need_imu=True):
    if os.path.exists(STOP_FILE):
        sys.exit(f"remove {STOP_FILE} first")
    lid = Lidar(); lid.start()
    imu = Imu() if need_imu else None
    mcu = Stm32()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3 and (lid.scan is None or mcu.row is None or (imu and imu.t == 0)):
        if imu and not imu.is_alive():
            imu.start()
        time.sleep(0.05)
    if imu and not imu.is_alive():
        imu.start()
    time.sleep(0.5)
    if lid.scan is None or mcu.row is None:
        mcu.close()
        sys.exit("LiDAR or STM32 not sending")
    if imu:                                        # gyro bias while standing still
        xs = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            xs.append(imu.gz); time.sleep(0.01)
        imu.bias = sum(xs) / len(xs); imu.yaw = 0.0
        print(f"gyro bias {math.degrees(imu.bias):+.2f} deg/s (removed)", flush=True)
    d, a = lid.nearest()
    print(f"nearest obstacle {d} mm at {a:.0f} deg; stop distance {args.stop_dist} mm", flush=True)
    if d < args.stop_dist:
        mcu.close()
        sys.exit("something is already inside the stop distance: clear the area")
    return lid, imu, mcu, Guard(lid, imu, mcu, args.stop_dist, args.max_s)


def run_loop(mcu, guard, step, hz=20):
    """Call step(t) -> (left_rpm, right_rpm) or None to finish, at hz, until done or the guard trips."""
    t0 = time.monotonic()
    nxt = t0
    reason = None
    try:
        while True:
            why = guard.check()
            if why:
                reason = why
                break
            cmd = step(time.monotonic() - t0)
            if cmd is None:
                break
            mcu.drive(*cmd)
            nxt += 1 / hz
            time.sleep(max(0.0, nxt - time.monotonic()))
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        mcu.stop()
    return reason


def ramp(t, total, peak, ramp_s=0.8):
    """Trapezoid: 0 -> peak over ramp_s, hold, back to 0 over ramp_s."""
    if t >= total:
        return None
    return peak * min(1.0, t / ramp_s, (total - t) / ramp_s)


def cmd_probe(args):
    lid, imu, mcu, guard = start(args, need_imu=False)
    before = [lid.per_degree() for _ in range(1)]
    time.sleep(0.3)
    before = lid.per_degree()
    (_, _), (c0l, c0r) = mcu.wheels()
    rpm = rpm_for(0.15)

    def step(t):
        v = ramp(t, 2.4, rpm)
        return None if v is None else (v, v)

    reason = run_loop(mcu, guard, step)
    time.sleep(0.8)
    after = lid.per_degree()
    (_, _), (c1l, c1r) = mcu.wheels()
    moved = ((c1l - c0l) + (c1r - c0r)) / 2 / COUNTS_PER_REV * WHEEL_C
    # robot moved `moved` m forward: ranges ahead shrink by ~moved, behind grow by ~moved
    diffs = [(i, after[i] - before[i]) for i in range(360) if before[i] < 8000 and after[i] < 8000]
    best, best_score = None, -1e9
    for f in range(0, 360, 2):                    # fit d_after - d_before ~= -moved*cos(angle - f)
        score = -sum(abs(dd + moved * 1000 * math.cos(math.radians(i - f))) for i, dd in diffs)
        if score > best_score:
            best, best_score = f, score
    print(f"moved {moved * 100:.1f} cm by the encoders" + (f" (stopped: {reason})" if reason else ""))
    print(f"robot front is at LiDAR angle ~{best} deg ({len(diffs)} degrees compared)")
    geo = json.load(open(CAL_FILE)) if os.path.exists(CAL_FILE) else {}
    geo["lidar_front_deg"] = best
    json.dump(geo, open(CAL_FILE, "w"), indent=1)
    mcu.close()


def cmd_spin(args):
    lid, imu, mcu, guard = start(args)
    rpm = args.spin_rpm
    samples = []

    def step(t):
        v = ramp(t, args.spin_s, rpm)
        if v is None:
            return None
        if 1.5 < t < args.spin_s - 1.0:
            (l, r), _ = mcu.wheels()
            samples.append((l, r, imu.gz))
        return (-v, v)                            # left back, right forward: spin left (CCW)

    time.sleep(0.3)
    before = lid.per_degree()
    reason = run_loop(mcu, guard, step)
    time.sleep(0.8)
    after = lid.per_degree()
    yaw = math.degrees(imu.yaw)
    # the scene rotates opposite to the robot: find the shift k with after[i] ~ before[i - k]
    best_k, best_err = 0, 1e18
    for k in range(360):
        err, n = 0.0, 0
        for i in range(0, 360, 2):
            x, y = after[i], before[(i - k) % 360]
            if x < 8000 and y < 8000:
                err += min(abs(x - y), 500); n += 1
        if n and err / n < best_err:
            best_k, best_err = k, err / n
    shift = (best_k + 180) % 360 - 180            # -180..180
    lidar_ccw = shift < 0                    # robot turned left (CCW): scene moves to lower angles if CCW-numbered
    l = sum(s[0] for s in samples) / len(samples); r = sum(s[1] for s in samples) / len(samples)
    gz = sum(s[2] for s in samples) / len(samples)
    vl, vr = l / 60 * WHEEL_C, r / 60 * WHEEL_C
    track = (vr - vl) / gz if gz else float("nan")
    print(f"spin left at {rpm:g} RPM per wheel: wheels L {l:+.1f} R {r:+.1f} RPM, gyro {math.degrees(gz):+.1f} deg/s, "
          f"total turn {yaw:+.0f} deg" + (f" (stopped: {reason})" if reason else ""))
    print(f"effective track width {track * 100:.1f} cm  (gyro sign: CCW/left turn is {'+' if gz > 0 else '-'})")
    print(f"LiDAR scene shifted {shift:+d} deg (match error {best_err:.0f} mm) for a {yaw:+.0f} deg gyro turn: "
          f"LiDAR angles increase {'counter-clockwise' if lidar_ccw else 'clockwise'}")
    geo = json.load(open(CAL_FILE)) if os.path.exists(CAL_FILE) else {}
    geo.update(track_m=abs(track), gyro_left_sign=1 if gz > 0 else -1, lidar_ccw=bool(lidar_ccw), spin_shift_deg=shift)
    json.dump(geo, open(CAL_FILE, "w"), indent=1)
    imu.close(); mcu.close()


def cmd_circle(args):
    geo = json.load(open(CAL_FILE))
    b, gsign = (args.track or geo["track_m"]), geo["gyro_left_sign"]
    lid, imu, mcu, guard = start(args)
    if args.lidar:
        lid.start_odometry()
        time.sleep(0.3)
    R, v = args.diameter / 2, args.speed
    turn = 1 if args.side == "left" else -1       # + = CCW
    w_target = turn * v / R                       # rad/s
    total = abs(2 * math.pi * args.laps)
    trace = []
    st = {"i": 0.0, "w": 0.0, "cmd": (0.0, 0.0), "slip_since": None, "stuck_since": None,
          "recover_until": 0.0, "recoveries": 0, "events": [], "ease_t": None}

    def step(t):
        yaw = imu.yaw * gsign                     # + = CCW
        done = abs(yaw) / total
        if done >= 1.0:
            return None
        # ease in over the first 1.5 s and out over the last ~15 deg
        k = min(1.0, t / 1.5, max(0.15, (total - abs(yaw)) / math.radians(15)))
        vk, wk = v * k, w_target * k
        v_true = lid.speed() if args.lidar else None
        if v_true is not None and t > 2.5:
            # Radius = true speed / turn rate. Turn at the rate the robot's REAL speed needs (slip-proof),
            # and if the turn lags (left turns lift the outer wheel), slow down so the radius still holds.
            wk = turn * v_true / R * min(1.0, k + 0.0)
            w_got = abs(imu.gz)
            if t > 5:
                vk = vk * min(1.0, max(0.35, 1.3 * w_got * R / max(v_true, 0.05)))
            st["v_true"] = v_true
        # yaw-rate feedback (PI) on top of the geometric feedforward: holds the radius despite slip
        w_meas = imu.gz * gsign
        (ml_now, mr_now), _ = mcu.wheels()
        if not args.open_loop and args.recover:
            # Lift / slip: a wheel running well above its command has lost the floor (seen: the outer
            # wheel lifting on this 4-wheel rigid chassis, after which the robot stops turning).
            cl_, cr_ = st["cmd"]
            # only mid-circle (k == 1): while the turn builds up the chassis drags the inner wheel above its
            # command, and while easing out the command drops faster than the wheels slow down
            slipping = t > 5 and k >= 1.0 and any(abs(m) > 1.4 * abs(c) + 4 for m, c in ((ml_now, cl_), (mr_now, cr_)))
            stuck = t > 6 and abs(w_meas) < 0.3 * abs(wk)
            now = time.monotonic()
            st["slip_since"] = (st["slip_since"] or now) if slipping else None
            st["stuck_since"] = (st["stuck_since"] or now) if stuck else None
            bad = ((st["slip_since"] and now - st["slip_since"] > 0.5) and "wheel slip/lift") or \
                  ((st["stuck_since"] and now - st["stuck_since"] > 2.0) and "not turning")
            if bad and now > st["recover_until"]:
                st["recoveries"] += 1
                st["events"].append((round(t, 1), bad, round(math.degrees(yaw))))
                print(f"  {t:5.1f} s: {bad} at {math.degrees(yaw):+.0f} deg -> recovery #{st['recoveries']}", flush=True)
                if st["recoveries"] > args.max_recoveries:
                    st["abort"] = f"{bad}: gave up after {args.max_recoveries} recoveries"
                    return None
                st["recover_until"] = now + (1.0 if args.recover_mode == "roll" else 0.5)
                st["i"] = 0.0
                st["slip_since"] = st["stuck_since"] = None
                st["ease_t"] = now
            if args.recover_mode == "roll" and now < st["recover_until"]:   # slow straight roll
                st["cmd"] = (rpm_for(0.3 * v), rpm_for(0.3 * v))
                return st["cmd"]
        if args.open_loop:                        # fixed wheel ratio, no gyro correction: measure the arc
            if t > args.open_s:
                return None
            vl, vr = vk - wk * b / 2, vk + wk * b / 2
            (ml, mr), (cl, cr) = mcu.wheels()
            trace.append((round(t, 2), round(math.degrees(yaw), 1), round(math.degrees(w_meas), 1), round(ml, 1), round(mr, 1), cl, cr))
            return rpm_for(vl), rpm_for(vr)
        err = wk - w_meas
        # The wheels take ~2-3 s to force a turn on this skid-steer chassis, so the yaw-rate correction
        # is gentle and only integrates once the turn is under way (anti-windup during the start).
        if t > 3.0:
            st["i"] = max(-0.15, min(0.15, st["i"] + err / 20))
        if t > 5 and yaw * turn < -math.radians(5):   # heading went the wrong way: conventions are off
            st["abort"] = f"turned the wrong way ({math.degrees(yaw):+.0f} deg)"
            return None
        w_cmd = wk + args.kp_yaw * err + args.ki_yaw * st["i"]
        if args.recover and args.recover_mode == "ease" and st["ease_t"] is not None:
            # traction control: after a lift/slip, halve the speed difference and ramp it back over 3 s,
            # so the chassis settles onto all four wheels instead of the outer wheel pushing harder
            e = min(1.0, 0.5 + (time.monotonic() - st["ease_t"]) / 6.0)
            w_cmd *= e
            st["i"] *= e if e < 1.0 else 1.0
        # cap the correction: the outer wheel never runs more than 15% above what the model asks for
        w_cmd = math.copysign(min(abs(w_cmd), abs(wk) * (1 + 0.15 * 2 * vk / (abs(wk) * b) if wk else 1)), w_cmd or wk or 1)
        vl, vr = vk - w_cmd * b / 2, vk + w_cmd * b / 2
        # never ask a wheel for exactly 0: the firmware then switches that motor off and it freewheels
        vl = vl if abs(vl) > 0.002 else math.copysign(0.002, vl or 1)
        vr = vr if abs(vr) > 0.002 else math.copysign(0.002, vr or 1)
        (ml, mr), (cl, cr) = mcu.wheels()
        trace.append((round(t, 2), round(math.degrees(yaw), 1), round(math.degrees(w_meas), 1), round(ml, 1), round(mr, 1), cl, cr,
                      round(st.get("v_true") or -1, 3), round(vk, 3)))
        st["cmd"] = (rpm_for(vl), rpm_for(vr))
        return st["cmd"]

    print(f"circle: diameter {args.diameter} m, {args.side}, {v} m/s, track {b * 100:.1f} cm -> wheels "
          f"L {rpm_for(v - w_target * b / 2):.1f} R {rpm_for(v + w_target * b / 2):.1f} RPM, "
          f"{math.degrees(w_target):+.1f} deg/s, ~{2 * math.pi / abs(w_target):.0f} s per lap", flush=True)
    reason = run_loop(mcu, guard, step) or st.get("abort")
    time.sleep(0.6)
    yaw = math.degrees(imu.yaw * gsign)
    _, (cl, cr) = mcu.wheels()
    dl = (cl - trace[0][5]) / COUNTS_PER_REV * WHEEL_C if trace else 0
    dr = (cr - trace[0][6]) / COUNTS_PER_REV * WHEEL_C if trace else 0
    path = (dl + dr) / 2
    print(f"turned {yaw:+.0f} deg; wheels travelled L {dl:.2f} m, R {dr:.2f} m, centre {path:.2f} m "
          f"(a {args.diameter} m circle is {math.pi * args.diameter * args.laps:.2f} m)"
          + (f"; STOPPED: {reason}" if reason else ""))
    if abs(yaw) > 10:
        print(f"radius from wheels and gyro: {path / math.radians(abs(yaw)):.2f} m (target {R:.2f} m)")
        steady = [r for r in trace if 2.0 < r[0] < (args.open_s - 1.0 if args.open_loop else 1e9)]
        if steady and args.open_loop:
            vl = sum(r[3] for r in steady) / len(steady) / 60 * WHEEL_C
            vr = sum(r[4] for r in steady) / len(steady) / 60 * WHEEL_C
            w = sum(r[2] for r in steady) / len(steady)
            print(f"steady part: wheels L {vl:.3f} R {vr:.3f} m/s, turn {w:+.1f} deg/s -> effective track "
                  f"{abs(vr - vl) / math.radians(abs(w)) * 100:.0f} cm (geometric {b * 100:.0f} cm)")
    if st["events"]:
        print(f"recoveries: {st['recoveries']}  events (t s, why, heading deg): {st['events']}")
    json.dump(trace, open(os.path.expanduser("~/motor_cal/circle_trace.json"), "w"))
    if args.lidar and len(lid.path) > 20:
        report_path(lid.path, trace, args)
    imu.close(); mcu.close()


def fit_circle(xy):
    """Least-squares circle (Kasa): centre (a, b), radius."""
    import numpy as np
    x, y = xy[:, 0], xy[:, 1]
    A = np.column_stack((x, y, np.ones_like(x)))
    c = np.linalg.lstsq(A, x * x + y * y, rcond=None)[0]
    a, b = c[0] / 2, c[1] / 2
    return a, b, math.sqrt(c[2] + a * a + b * b)


def report_path(path, trace, args):
    """True path from LiDAR odometry vs the wheel/gyro dead-reckoned path; fitted circle; PNG plot."""
    import numpy as np
    P = np.array([(p[1], p[2]) for p in path])
    bad = sum(1 for p in path if not p[4])
    a, b, r = fit_circle(P)
    closure = math.hypot(P[-1, 0] - P[0, 0], P[-1, 1] - P[0, 1])
    dist = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
    # wheel + gyro dead reckoning
    W = [(0.0, 0.0)]
    for t0, t1 in zip(trace, trace[1:]):
        ds = ((t1[5] - t0[5]) + (t1[6] - t0[6])) / 2 / COUNTS_PER_REV * WHEEL_C
        h = math.radians(t1[1])
        W.append((W[-1][0] + ds * math.cos(h), W[-1][1] + ds * math.sin(h)))
    W = np.array(W)
    wdist = float(np.sum(np.hypot(*np.diff(W, axis=0).T)))
    print(f"LiDAR path: {dist:.2f} m, fitted circle diameter {2 * r:.2f} m (target {args.diameter} m), "
          f"ends {closure * 100:.0f} cm from the start; wheels say {wdist:.2f} m -> slip {(1 - dist / wdist) * 100:+.0f}%; "
          f"{bad} of {len(path)} scans unmatched", flush=True)
    stamp = time.strftime("%H%M%S")
    np.save(os.path.expanduser(f"~/motor_cal/lidar_path_{stamp}.npy"), np.array([p[:4] for p in path]))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(P[:, 0], P[:, 1], lw=2, label=f"LiDAR (true) path, {dist:.2f} m")
        ax.plot(W[:, 0], W[:, 1], lw=1, ls="--", label=f"wheels + gyro, {wdist:.2f} m")
        th = np.linspace(0, 2 * math.pi, 200)
        ax.plot(a + r * np.cos(th), b + r * np.sin(th), lw=0.8, color="grey", label=f"fitted circle, {2 * r:.2f} m")
        ax.plot([0], [0], "ko", label="start")
        ax.set_aspect("equal"); ax.grid(alpha=0.3); ax.legend(loc="best", fontsize=8)
        ax.set_xlabel("x, m (start heading)"); ax.set_ylabel("y, m (left)")
        ax.set_title(f"{args.side} circle, target {args.diameter} m, {args.speed} m/s")
        out = os.path.expanduser(f"~/motor_cal/circle_{args.side}_{stamp}.png")
        fig.savefig(out, dpi=110, bbox_inches="tight")
        print(f"plot: {out}", flush=True)
    except Exception as e:
        print(f"plot failed: {e!r}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("probe", "spin", "circle"))
    ap.add_argument("--stop-dist", type=int, default=500, help="mm: stop if anything is closer (default 500)")
    ap.add_argument("--max-s", type=float, default=60, help="hard time limit per run")
    ap.add_argument("--spin-rpm", type=float, default=15)
    ap.add_argument("--spin-s", type=float, default=8)
    ap.add_argument("--diameter", type=float, default=2.0)
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--speed", type=float, default=0.25, help="m/s along the circle")
    ap.add_argument("--laps", type=float, default=1)
    ap.add_argument("--track", type=float, default=None, help="m, override the calibrated track width")
    ap.add_argument("--open-loop", action="store_true", help="fixed wheel ratio, no gyro correction")
    ap.add_argument("--open-s", type=float, default=7, help="seconds to run with --open-loop")
    ap.add_argument("--no-lidar", dest="lidar", action="store_false",
                    help="don't use LiDAR odometry (true speed) to hold the radius")
    ap.add_argument("--no-recover", dest="recover", action="store_false",
                    help="don't detect wheel lift/slip and recover (just run)")
    ap.add_argument("--max-recoveries", type=int, default=8)
    ap.add_argument("--recover-mode", choices=("ease", "roll"), default="ease",
                    help="ease: halve the speed difference and ramp it back (traction control); roll: straight roll")
    ap.add_argument("--kp-yaw", type=float, default=0.4, help="yaw-rate correction, proportional")
    ap.add_argument("--ki-yaw", type=float, default=1.0, help="yaw-rate correction, integral")
    a = ap.parse_args()
    {"probe": cmd_probe, "spin": cmd_spin, "circle": cmd_circle}[a.mode](a)


if __name__ == "__main__":
    main()
