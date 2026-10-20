#!/usr/bin/env python3
"""Demo worker: STM32 motor controller over its serial link (115200 baud).

The port is --port: today the FTDI USB-serial adapter (/dev/ttyUSB0); a direct UART to the STM32
later (e.g. /dev/ttyAMA3 with the matching dtoverlay). Nothing else here depends on which it is.

Sends a target-RPM command at 20 Hz and times the firmware's "OK target" reply, and follows the
telemetry stream (tgt/meas/duty/cap/cnt). While it runs, telemetry is at 50 Hz so each line carries
the board's own millisecond clock (t=), which gives the telemetry delivery latency. On exit it
sends "stop" and puts telemetry back to 10 Hz, like pwm-lab5/motor_live.py.

Safety: the target is 0 RPM unless --rpm is given. It never sends cap/open/kp/ki/kd/reset.
Only one program can hold the port: close motor_live.py / motor_pid_uart.py first.
"""
import argparse
import collections
import re
import threading
import time

import serial

from bus import Pub, Window, every, install_stop, now

BAUD, CMD_HZ, TEL_HZ = 115200, 20, 50
TEL = re.compile(rb"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+)(.*)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpm", type=float, default=0.0, help="target RPM to hold (default 0: motor stays still)")
    ap.add_argument("--port", default="/dev/ttyUSB0", help="serial port to the STM32 (default %(default)s)")
    a = ap.parse_args()
    stop = install_stop()
    pub = Pub("motor")
    rtt, period, delivery = Window(0.5), Window(0.5), Window(0.5)
    st = {"cmds": 0, "acks": 0, "timeouts": 0, "errs": 0, "tel": 0, "ore": 0, "faults": 0, "last_tel": 0.0,
          "t0": now(), "c0": 0, "n0": 0, "offs": collections.deque(), "latest": None, "last_pub": 0.0}

    def stats():
        t = now()
        dt = max(1e-6, t - st["t0"])
        pub.send("stats", cmd_hz=round((st["acks"] - st["c0"]) / dt, 1), tel_hz=round((st["tel"] - st["n0"]) / dt, 1),
                 cmd_rtt_ms=rtt.summary(), telem_period_ms=period.summary(), telem_delivery_ms=delivery.summary(),
                 commands=st["cmds"], timeouts=st["timeouts"], err_replies=st["errs"], overruns=st["ore"],
                 target_rpm=a.rpm)
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
                    extra = m.group(6).decode(errors="replace")
                    tm = re.search(r"\bt=(\d+)", extra)
                    if tm:                                   # board ms clock: delivery above best case
                        off = t * 1e3 - int(tm.group(1))
                        offs = st["offs"]
                        offs.append((t, off))
                        while offs and offs[0][0] < t - 5:
                            offs.popleft()
                        delivery.add(off - min(o for _, o in offs), t)
                    om = re.search(r"ORE=(\d+)", extra)
                    if om:
                        st["ore"] = int(om.group(1))
                    if "FAULT" in extra:
                        st["faults"] += 1
                    if t - st["last_pub"] >= 0.1:
                        st["last_pub"] = t
                        pub.send("data", tgt=float(m.group(1)), meas=float(m.group(2)), duty=float(m.group(3)),
                                 cap=float(m.group(4)), cnt=int(m.group(5)),
                                 flags=[f for f in ("OPEN", "FAULT:STALL") if f in extra])
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
            pub.status("ok", f"target {a.rpm:g} RPM, commanded {CMD_HZ}x per second; telemetry {TEL_HZ} Hz")
            nxt = now()
            while not stop.is_set():
                acked.clear()
                pending["t"] = now()
                ser.write(f"{a.rpm:g}\n".encode())
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
