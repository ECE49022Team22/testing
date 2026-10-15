#!/usr/bin/env python3
"""STM32 motor PID link over the FTDI USB-UART (pwm-lab5 MOTOR_PID_DEMO firmware), instrumented.

Sends a target-RPM command at --rate Hz and times the firmware's "OK target" reply, while a
reader thread timestamps the 10 Hz telemetry stream (same split as motor_pid_uart.py).
Default target is 0 RPM so the motor doesn't move; pass e.g. --rpm 0 5 to alternate.

Metrics
  cmd_rtt_ms        write("<rpm>\\n") -> "OK target ..." line received
  telem_period_ms   time between telemetry lines (ideal 100 ms)
"""
import threading
import time

import serial

from common import Recorder, base_args, log, now


def main():
    ap = base_args(__doc__)
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--rpm", type=float, nargs="+", default=[0.0])
    a = ap.parse_args()
    rec = Recorder("motor", a.out)

    ser = serial.Serial(a.port, a.baud, timeout=0.2)
    ser.reset_input_buffer()
    try:
        with open(f"/sys/bus/usb-serial/devices/{a.port.rsplit('/', 1)[-1]}/latency_timer") as f:
            rec.info["ftdi_latency_timer_ms"] = int(f.read())
    except OSError:
        pass
    pending = {"t": None}
    got_ok = threading.Event()

    def reader():
        last_telem = None
        while not rec.stopping:
            line = ser.readline()
            t = now()
            if not line.endswith(b"\n"):
                continue
            if line.startswith(b"tgt="):
                if last_telem is not None:
                    rec.add("telem_period_ms", (t - last_telem) * 1e3, t)
                last_telem = t
                rec.count("telemetry")
                if b"FAULT" in line:
                    rec.count("fault_lines")
            elif line.startswith(b"OK target") and pending["t"] is not None:
                rec.add("cmd_rtt_ms", (t - pending["t"]) * 1e3, t)
                pending["t"] = None
                got_ok.set()
            elif line.startswith(b"ERR"):
                rec.count("err_replies")

    threading.Thread(target=reader, daemon=True).start()
    rec.ready()
    period = 1.0 / a.rate
    nxt = now()
    i = 0
    try:
        while not rec.stopping:
            rpm = a.rpm[i % len(a.rpm)]
            i += 1
            got_ok.clear()
            pending["t"] = now()
            ser.write(f"{rpm:g}\n".encode())
            if not got_ok.wait(0.5):
                rec.count("timeouts")
                pending["t"] = None
            nxt += period
            delay = nxt - now()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = now()
                rec.count("overruns")
    finally:
        try:
            ser.write(b"stop\n")
        except Exception:
            pass
        rec.dump()


if __name__ == "__main__":
    main()
