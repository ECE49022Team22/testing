#!/usr/bin/env python3
"""Demo worker: STM32 motor controller (two drive motors) over its serial link (115200 baud).

The port is --port: today the FTDI USB-serial adapter (/dev/ttyUSB0); a direct UART to the STM32
later (e.g. /dev/ttyAMA3 with the matching dtoverlay). Nothing else here depends on which it is.

Sends both wheel targets in one "d <rpm1> <rpm2>" command at 20 Hz and times the firmware's
"OK target" reply, and follows the telemetry stream (tgt/meas/duty/cap/cnt, then tgt2/.../cnt2 for
motor 2). While it runs, telemetry is at 50 Hz so each line carries the board's own millisecond
clock (t=), which gives the telemetry delivery latency; if the board resets (and drops back to
10 Hz) it's set again. On exit it sends "stop" and puts telemetry back to 10 Hz, like
pwm-lab5/motor_live.py.

Wheels: targets are in the robot's frame, left and right wheel RPM with + = robot forward.
--left-motor says which STM32 motor is the left wheel (the other is the right), and --left-sign /
--right-sign flip a wheel whose motor is mounted the other way round (on most chassis the two
motors face opposite directions, so one of them turns backwards to drive the robot forward).

Dashboard control: the hub forwards the dashboard's commands here as UDP on localhost (CONTROL_PORT):
{"drive": [left, right]} sets both wheels, {"rpm": x} sets both to x, {"cmd": "stop"} goes to 0,
{"cmd": "reset"} clears latched stall faults. The firmware holds its last targets forever, so a
dashboard target is a lease: it lapses back to --rpm unless the page renews it within LEASE_S
(a closed tab or a lost network link stops the motors).

Safety: the targets are 0 RPM unless --rpm is given or the dashboard sets them, and each is
clamped to +/- --max-rpm. It never sends cap/open/kp/ki/kd. Only one program can hold the port:
close motor_live.py / motor_pid_uart.py first.
"""
import argparse
import collections
import json
import re
import socket
import threading
import time

import serial

from bus import Pub, Window, every, install_stop, now

# A two-motor telemetry line is ~150 bytes, ~13 ms on the wire at 115200 baud, and a command ack that
# arrives while one is going out waits behind it: ack p99 ~13 ms with two motors (~3 ms with one).
# That's the line's length, not the rate (25 Hz measured no better), so telemetry stays at 50 Hz.
BAUD, CMD_HZ, TEL_HZ = 115200, 20, 50
CONTROL_PORT = 8766                     # hub -> motor worker, localhost only
LEASE_S = 1.0                           # a dashboard target lapses unless renewed this often
NUM, INT = rb"(-?[\d.]+)", rb"(-?\d+)"
TEL = re.compile(rb"tgt=%s meas=%s duty=%s%% cap=%s%% cnt=%s tgt2=%s meas2=%s duty2=%s%% cap2=%s%% cnt2=%s(.*)"
                 % (NUM, NUM, NUM, NUM, INT, NUM, NUM, NUM, NUM, INT))
FIELDS = ("tgt", "meas", "duty", "cap", "cnt")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpm", type=float, default=0.0,
                    help="wheel RPM to hold, both wheels, + = forward (default 0: the motors stay still)")
    ap.add_argument("--port", default="/dev/ttyUSB0", help="serial port to the STM32 (default %(default)s)")
    ap.add_argument("--max-rpm", type=float, default=175.0,
                    help="largest |target| accepted from anywhere (with the wheels on, 100%% duty is ~195 RPM)")
    ap.add_argument("--left-motor", type=int, choices=(1, 2), default=2,
                    help="STM32 motor driving the left wheel (default 2, checked on the floor 2026-11-04)")
    ap.add_argument("--left-sign", type=int, choices=(1, -1), default=1,
                    help="-1 if the left motor's + direction drives the robot backwards")
    ap.add_argument("--right-sign", type=int, choices=(1, -1), default=-1,
                    help="-1 (default) if the right motor's + direction drives the robot backwards")
    a = ap.parse_args()
    clamp = lambda v: float(max(-a.max_rpm, min(a.max_rpm, v)))
    a.rpm = clamp(a.rpm)
    wheel_motor = {"left": a.left_motor, "right": 3 - a.left_motor}
    wheel_sign = {"left": a.left_sign, "right": a.right_sign}

    def to_motors(left, right):
        """Wheel targets (robot frame) -> (motor 1, motor 2) targets."""
        m = {}
        for w, v in (("left", left), ("right", right)):
            m[wheel_motor[w]] = v * wheel_sign[w] + 0.0   # + 0.0: no "-0" on the wire
        return m[1], m[2]

    stop = install_stop()
    pub = Pub("motor")
    rtt, period, delivery = Window(0.5), Window(0.5), Window(0.5)
    st = {"cmds": 0, "acks": 0, "timeouts": 0, "errs": 0, "tel": 0, "ore": 0, "faults": 0, "last_tel": 0.0,
          "t0": now(), "c0": 0, "n0": 0, "offs": collections.deque(), "latest": None, "last_pub": 0.0}
    ctl = {"drive": None, "until": 0.0, "reset": False, "need_rate": False}   # dashboard targets and their lease

    def target():
        """(left, right) wheel RPM, and who set them."""
        if ctl["drive"] is not None and now() < ctl["until"]:
            return ctl["drive"], "dashboard"
        ctl["drive"] = None
        return (a.rpm, a.rpm), "command line"

    def control():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", CONTROL_PORT))
        sock.settimeout(0.5)
        while not stop.is_set():
            try:
                msg = json.loads(sock.recv(512))
            except socket.timeout:
                continue
            except (OSError, ValueError):
                continue
            ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v   # not NaN
            cmd, drive = msg.get("cmd"), msg.get("drive")
            if cmd == "stop":
                ctl["drive"], ctl["until"] = (0.0, 0.0), now() + LEASE_S
            elif cmd == "reset":
                ctl["reset"] = True
            elif isinstance(drive, list) and len(drive) == 2 and all(map(ok, drive)):
                ctl["drive"], ctl["until"] = (clamp(drive[0]), clamp(drive[1])), now() + LEASE_S
            elif ok(msg.get("rpm")):
                ctl["drive"], ctl["until"] = (clamp(msg["rpm"]),) * 2, now() + LEASE_S

    threading.Thread(target=control, daemon=True).start()

    def stats():
        t = now()
        dt = max(1e-6, t - st["t0"])
        pub.stats(cmd_hz=round((st["acks"] - st["c0"]) / dt, 1), tel_hz=round((st["tel"] - st["n0"]) / dt, 1),
                 cmd_rtt_ms=rtt.summary(), telem_period_ms=period.summary(), telem_delivery_ms=delivery.summary(),
                 commands=st["cmds"], timeouts=st["timeouts"], err_replies=st["errs"], overruns=st["ore"],
                 target_left=target()[0][0], target_right=target()[0][1], source=target()[1], max_rpm=a.max_rpm,
                 wheels={w: {"motor": wheel_motor[w], "sign": wheel_sign[w]} for w in ("left", "right")})
        st["t0"], st["c0"], st["n0"] = t, st["acks"], st["tel"]
        if st["last_tel"] and t - st["last_tel"] > 2:
            pub.status("nodata", f"no telemetry from the STM32 for {t - st['last_tel']:.0f} s")

    every(0.5, stats, stop)
    while not stop.is_set():
        try:
            ser = serial.Serial(a.port, BAUD, timeout=0.2)
        except Exception as e:
            pub.status("disconnected", f"serial link to the STM32 ({a.port}): {e}")
            stop.wait(5)
            continue
        pending = {"t": None}
        acked = threading.Event()
        alive = threading.Event()
        alive.set()

        def reader():
            last = None
            while alive.is_set():
                try:
                    line = ser.readline()
                except Exception:
                    break
                t = now()
                if not line.endswith(b"\n"):
                    continue
                m = TEL.match(line)
                if m:
                    st["tel"] += 1
                    st["last_tel"] = t
                    if last is not None:
                        period.add((t - last) * 1e3, t)
                    last = t
                    extra = m.group(11).decode(errors="replace")
                    tm = re.search(r"\bt=(\d+)", extra)
                    if not tm:                               # board reset back to 10 Hz: ask for 50 again
                        ctl["need_rate"] = True
                    else:                                    # board ms clock: delivery above best case
                        off = t * 1e3 - int(tm.group(1))
                        offs = st["offs"]
                        offs.append((t, off))
                        while offs and offs[0][0] < t - 5:
                            offs.popleft()
                        delivery.add(off - min(o for _, o in offs), t)
                    om = re.search(r"ORE=(\d+)", extra)
                    if om:
                        st["ore"] = int(om.group(1))
                    if t - st["last_pub"] >= 0.1:
                        st["last_pub"] = t
                        g = m.groups()
                        motors = {1: dict(zip(FIELDS, map(float, g[0:5]))), 2: dict(zip(FIELDS, map(float, g[5:10])))}
                        motors[1]["flags"] = [f for f, k in (("open-loop", " OPEN"), ("stall", " FAULT:STALL")) if k in extra]
                        motors[2]["flags"] = [f for f, k in (("open-loop", " open2"), ("stall", " stall2")) if k in extra]
                        wheels = {}
                        for w in ("left", "right"):
                            mo, sg = motors[wheel_motor[w]], wheel_sign[w]
                            wheels[w] = {"motor": wheel_motor[w], "tgt": mo["tgt"] * sg, "meas": mo["meas"] * sg,
                                         "duty": mo["duty"] * sg, "cap": mo["cap"], "cnt": int(mo["cnt"]), "flags": mo["flags"]}
                        pub.send("data", **wheels)
                elif line.startswith(b"OK target") and pending["t"] is not None:
                    rtt.add((t - pending["t"]) * 1e3, t)
                    pending["t"] = None
                    st["acks"] += 1
                    acked.set()
                elif line.startswith(b"ERR"):
                    st["errs"] += 1

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        try:
            ser.write(f"rate {TEL_HZ}\n".encode())
            pub.status("ok", f"both wheels commanded {CMD_HZ}x per second (limit ±{a.max_rpm:g} RPM); telemetry {TEL_HZ} Hz")
            nxt = now()
            while not stop.is_set():
                if ctl["reset"]:
                    ctl["reset"] = False
                    ser.write(b"reset\n")
                if ctl["need_rate"]:
                    ctl["need_rate"] = False
                    ser.write(f"rate {TEL_HZ}\n".encode())
                m1, m2 = to_motors(*target()[0])
                acked.clear()
                pending["t"] = now()
                ser.write(f"d {m1:g} {m2:g}\n".encode())
                st["cmds"] += 1
                if not acked.wait(0.5):
                    st["timeouts"] += 1
                    pending["t"] = None
                nxt += 1 / CMD_HZ
                stop.wait(max(0.0, nxt - now()))
                if nxt < now() - 1:
                    nxt = now()
        except Exception as e:
            pub.status("error", f"{type(e).__name__}: {e}")
            stop.wait(2)
        finally:
            try:                                          # leave the board as we found it
                ser.write(b"stop\n")
                time.sleep(0.05)
                ser.write(b"rate 10\n")
                time.sleep(0.05)
            except Exception:
                pass
            alive.clear()
            th.join(timeout=1)
            ser.close()


if __name__ == "__main__":
    main()
