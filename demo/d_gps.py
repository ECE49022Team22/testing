#!/usr/bin/env python3
"""Demo worker: UM982 GNSS on UART0 (/dev/ttyAMA0 @ 230400), PPS on GPIO18 (/dev/pps1).

Publishes every GGA (fix, satellites, HDOP, position) and, every 0.5 s, the sentence rates and the
GGA timing error: how far each 5 Hz fix lands from its grid (the receiver emits on a fixed grid,
so any spread is added by the UART, kernel and scheduling). With a fix, also PPS -> GGA latency.
"""
import fcntl
import os
import struct
import threading
import time

import serial

from bus import Pub, Window, every, install_stop, now

PORT, BAUD, PPS_DEV = "/dev/ttyAMA0", 230400, "/dev/pps1"
PPS_FETCH = 0xC00870A4
PPS_FDATA = struct.Struct("<IIqiIqiIi4xqiI")
FIX = {0: "no fix", 1: "GPS", 2: "DGPS", 4: "RTK fixed", 5: "RTK float", 6: "dead reckoning"}


def nmea_ok(line):
    try:
        body, cs = line[1:].split(b"*")
        x = 0
        for b in body:
            x ^= b
        return int(cs[:2], 16) == x
    except ValueError:
        return False


def coord(v, hemi, deg_digits):
    if not v:
        return None
    d = float(v[:deg_digits]) + float(v[deg_digits:]) / 60
    return round(-d if hemi in ("S", "W") else d, 7)


def pps_thread(st, stop):
    try:
        fd = os.open(PPS_DEV, os.O_RDWR)
    except OSError:
        return
    while not stop.is_set():
        buf = bytearray(PPS_FDATA.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0))
        try:
            fcntl.ioctl(fd, PPS_FETCH, buf, True)
        except OSError:
            continue
        f = PPS_FDATA.unpack(buf)
        if f[0] != st["pps_seq"]:
            st["pps_seq"], st["pps_t"], st["pps_used"] = f[0], f[2] + f[3] * 1e-9, False
            st["pps"] += 1


def main():
    stop = install_stop()
    pub = Pub("gps")
    jitter, pps_lat, gga_times = Window(), Window(10), Window()
    st = {"lines": 0, "bad": 0, "gga": 0, "pps": 0, "pps_seq": None, "pps_t": 0.0, "pps_used": True,
          "last_line": 0.0, "t0": now(), "l0": 0, "g0": 0}
    threading.Thread(target=pps_thread, args=(st, stop), daemon=True).start()

    def stats():
        t = now()
        dt = max(1e-6, t - st["t0"])
        pub.send("stats", lines_s=round((st["lines"] - st["l0"]) / dt, 1), gga_hz=round((gga_times.summary() or {"n": 0})["n"] / gga_times.span, 1),
                 gga_jitter_ms=jitter.summary(), pps_to_gga_ms=pps_lat.summary(), pps_pulses=st["pps"],
                 bad_lines=st["bad"])
        st["t0"], st["l0"], st["g0"] = t, st["lines"], st["gga"]
        if st["last_line"] and t - st["last_line"] > 3:
            pub.status("nodata", f"no NMEA on {PORT} for {t - st['last_line']:.0f} s")

    every(0.5, stats, stop)
    while not stop.is_set():
        try:
            s = serial.Serial(PORT, BAUD, timeout=0.5)
        except Exception as e:
            pub.status("disconnected", f"{PORT}: {e}")
            stop.wait(5)
            continue
        pub.status("starting", f"reading {PORT} @ {BAUD}")
        s.reset_input_buffer()
        last_gga, periods = None, []
        try:
            while not stop.is_set():
                line = s.readline()
                t = now()
                if not line.endswith(b"\n"):
                    continue
                if not line.startswith(b"$") or not nmea_ok(line.strip()):
                    st["bad"] += 1
                    continue
                st["lines"] += 1
                if not st["last_line"] or t - st["last_line"] > 3:
                    pub.status("ok", f"UM982 on {PORT} @ {BAUD}, 5 Hz")
                st["last_line"] = t
                if line[3:6] != b"GGA":
                    continue
                st["gga"] += 1
                gga_times.add(0, t)
                if last_gga is not None:
                    p = (t - last_gga) * 1e3
                    periods = (periods + [p])[-50:]
                    nominal = round(sorted(periods)[len(periods) // 2] / 50) * 50 or p
                    jitter.add(abs(p - nominal), t)
                last_gga = t
                if st["pps_used"] is False:
                    st["pps_used"] = True
                    lat = (time.time() - st["pps_t"]) * 1e3
                    if 0 <= lat < 1000:
                        pps_lat.add(lat, t)
                f = line.decode(errors="replace").split("*")[0].split(",")
                q = int(f[6]) if f[6].isdigit() else 0
                pub.send("data", fix=FIX.get(q, str(q)), quality=q, sats=int(f[7]) if f[7].isdigit() else 0,
                         hdop=float(f[8]) if f[8] else None, lat=coord(f[2], f[3], 2), lon=coord(f[4], f[5], 3),
                         alt_m=float(f[9]) if f[9] else None, utc=f[1] or None)
        except Exception as e:
            pub.status("error", f"{type(e).__name__}: {e}")
            stop.wait(2)
        finally:
            s.close()


if __name__ == "__main__":
    main()
