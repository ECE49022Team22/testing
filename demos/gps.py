"""Satellite position fixes and RTK (requirements 5-1, 5-3 and 5-5).

Prints every position reading from the GPS receiver as it arrives (5 per second): the time since the
previous one, the fix type (GPS / RTK float / RTK fixed), satellites, HDOP, the age of the RTK corrections
and the position. Cover the antenna with a hand or a metal bowl to show the fix degrading or stopping.

    .venv/bin/python demos/gps.py          # receiver only
    .venv/bin/python demos/gps.py --rtk    # also stream RTK corrections from the internet (~/.config/ntrip.json)
"""
import collections
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repo folder
import ntrip_rtk                               # noqa: E402  (our receiver reader and NTRIP client)

FIX_NAMES = {"0": "no fix", "1": "GPS", "2": "DGPS", "4": "RTK fixed", "5": "RTK float", "6": "dead reckoning"}

receiver = ntrip_rtk.Receiver("/dev/ttyAMA0", 230400, "/dev/ttyAMA4")   # NMEA in on UART0, corrections out on UART4

if "--rtk" in sys.argv:
    config = json.load(open(os.path.expanduser("~/.config/ntrip.json")))
    status = {"state": "starting", "bytes": 0, "connects": 0, "last_data": 0.0, "types": collections.Counter()}
    threading.Thread(target=ntrip_rtk.ntrip, args=(config, receiver, status, threading.Event()), daemon=True).start()
    print(f"Streaming RTK corrections from {config['host']}/{config['mountpoint']}")

print("Every position reading ($GNGGA) as it arrives:\n")
start = time.monotonic()
last_line, last_time = None, None
try:
    while True:
        if receiver.gga is not None and receiver.gga != last_line:      # a new reading
            now = time.monotonic()
            last_line = receiver.gga
            f = last_line.decode(errors="replace").split("*")[0].split(",")
            # $GNGGA, time, lat, N/S, lon, E/W, fix type, satellites, HDOP, altitude, ..., correction age
            fix = FIX_NAMES.get(f[6], f[6]) if len(f) > 6 else "?"
            sats = f[7] if len(f) > 7 else "?"
            hdop = f[8] if len(f) > 8 and f[8] else "-"
            age = f[13] if len(f) > 13 and f[13] else "-"
            if len(f) > 5 and f[2] and f[4]:                            # ddmm.mmmm -> decimal degrees
                lat = (int(f[2][:2]) + float(f[2][2:]) / 60) * (-1 if f[3] == "S" else 1)
                lon = (int(f[4][:3]) + float(f[4][3:]) / 60) * (-1 if f[5] == "W" else 1)
                where = f"{lat:.7f}, {lon:.7f}"
            else:
                where = "no position"
            gap = f"+{(now - last_time) * 1000:4.0f} ms" if last_time else "   first"
            print(f"{now - start:6.1f} s  {gap}   {fix:10s}  {sats:>2s} sats  HDOP {hdop:>4s}  "
                  f"corr. age {age:>4s} s   {where}")
            last_time = now
        time.sleep(0.005)
except KeyboardInterrupt:
    pass
