#!/usr/bin/env python3
"""UM982 NMEA on the Pi's UART0 (pin 8 TX -> GPS RX, pin 10 RX <- GPS TX), instrumented.

Metrics
  gga_period_ms   time between successive GGA sentences (receiver emits on a fixed grid,
                  so any spread is added by UART/kernel/scheduling)
  line_gap_ms     time between any two consecutive NMEA lines
  pps_to_gga_ms   PPS edge -> first GGA of that second arrives (only with --pps and a fix)
"""
import fcntl
import os
import struct
import threading
import time

import serial

from common import Recorder, base_args, log, now

PPS_FETCH = 0xC00870A4          # _IOWR('p', 0xa4, struct pps_fdata *)
PPS_FDATA = struct.Struct("<IIqiIqiIi4xqiI")   # kinfo (assert/clear seq + times + mode) + timeout


def pps_thread(dev, state, rec):
    fd = os.open(dev, os.O_RDWR)
    while not rec.stopping:
        buf = bytearray(PPS_FDATA.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0))   # 1 s timeout
        try:
            fcntl.ioctl(fd, PPS_FETCH, buf, True)
        except OSError:
            continue                    # timeout: no pulse (no fix yet)
        f = PPS_FDATA.unpack(buf)
        seq, sec, nsec = f[0], f[2], f[3]
        if seq != state.get("seq"):
            state["seq"] = seq
            state["t"] = sec + nsec * 1e-9          # CLOCK_REALTIME
            state["used"] = False
            rec.count("pps_pulses")


def main():
    ap = base_args(__doc__)
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--pps", default="", help="e.g. /dev/pps1 from dtoverlay=pps-gpio,gpiopin=18")
    a = ap.parse_args()
    rec = Recorder("gps", a.out)

    s = serial.Serial(a.port, a.baud, timeout=0.5)
    s.reset_input_buffer()
    pps = {}
    if a.pps and os.path.exists(a.pps):
        threading.Thread(target=pps_thread, args=(a.pps, pps, rec), daemon=True).start()
        rec.info["pps"] = a.pps
    rec.ready()
    last_line = last_gga = None
    try:
        while not rec.stopping:
            line = s.readline()
            t = now()
            if not line.endswith(b"\n"):
                continue
            if not line.startswith(b"$"):
                rec.count("bad_lines")
                continue
            rec.count("lines")
            if last_line is not None:
                rec.add("line_gap_ms", (t - last_line) * 1e3, t)
            last_line = t
            if line[3:6] == b"GGA":
                if last_gga is not None:
                    rec.add("gga_period_ms", (t - last_gga) * 1e3, t)
                last_gga = t
                if b",,,,,," not in line:
                    rec.count("gga_with_fix")
                if pps.get("used") is False:
                    pps["used"] = True
                    lat = (time.time() - pps["t"]) * 1e3
                    if 0 <= lat < 1000:
                        rec.add("pps_to_gga_ms", lat, t)
    finally:
        rec.dump()
        s.close()


if __name__ == "__main__":
    main()
