"""LiDAR scan rate and coverage (requirement 6-1).

Prints every full 360-degree scan as it arrives: its timestamp, the time since the previous scan, how
many points it had, how much of the circle it covered, and the nearest and farthest return. At the end:
the first and last scan timestamps and the rate worked out from them.

    .venv/bin/python demos/lidar_rate.py        # runs for 10 s
    .venv/bin/python demos/lidar_rate.py 30     # runs for 30 s
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repo folder
import lidar                                                                       # noqa: E402  (our STL-27L driver)

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0


def clock(t):
    """Wall-clock time with milliseconds, e.g. 17:42:05.317."""
    return datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]


sensor = lidar.STL27L("/dev/ttyAMA2")
print("LiDAR on /dev/ttyAMA2. One line per scan:\n")

first = last = None
count = 0
for scan in sensor.scans():                    # each scan is a list of (angle in degrees, distance in mm, intensity)
    now = time.time()
    count += 1
    distances_m = [d / 1000 for angle, d, intensity in scan if d > 0]
    degrees_covered = len({int(angle) % 360 for angle, d, intensity in scan})
    gap = f"+{(now - last) * 1000:5.1f} ms" if last else "   first "
    print(f"scan {count:3d}  {clock(now)}  {gap}   {len(scan):4d} points   covers {degrees_covered:3d} of 360 deg   "
          f"nearest {min(distances_m):5.2f} m   farthest {max(distances_m):5.1f} m")
    if first is None:
        first = now
    last = now
    if now - first >= SECONDS:
        break

print(f"\nfirst scan {clock(first)}, last scan {clock(last)}: {count - 1} scan intervals in {last - first:.3f} s"
      f"  ->  {count - 1} / {last - first:.3f} s = {(count - 1) / (last - first):.2f} scans per second")
