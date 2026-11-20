"""LiDAR obstacle detection ahead of the robot (requirements 6-2 and 8-1).

Shows the distance to the nearest thing in front of the robot (within 30 degrees of straight ahead),
updated with every scan. Walk in front of the robot, or hold a box in front of it, and watch it change.

    .venv/bin/python demos/lidar_obstacle.py        # Ctrl-C to stop
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import lidar                                   # noqa: E402  (our STL-27L driver)
from lidar_odom import FRONT_DEG               # noqa: E402  (the LiDAR angle that points at the robot's front)

HALF_WIDTH_DEG = 30        # "ahead" means within this many degrees of straight ahead
ROBOT_ITSELF_MM = 150      # returns closer than this are the robot's own frame
WARN_M = 1.0               # say OBSTACLE when something ahead is closer than this

sensor = lidar.STL27L("/dev/ttyAMA2")
print(f"Nearest thing within {HALF_WIDTH_DEG} degrees of straight ahead (front = LiDAR angle {FRONT_DEG}).\n")

try:
    for scan in sensor.scans():                # each scan is a list of (angle in degrees, distance in mm, intensity)
        ahead_mm = []
        for angle, d, intensity in scan:
            off_by = abs((angle - FRONT_DEG + 180) % 360 - 180)     # degrees away from straight ahead
            if off_by <= HALF_WIDTH_DEG and d > ROBOT_ITSELF_MM:
                ahead_mm.append(d)

        if not ahead_mm:
            print("\rnothing ahead" + " " * 70, end="", flush=True)
            continue

        nearest_m = min(ahead_mm) / 1000
        bar = "#" * int(min(nearest_m, 5.0) * 10)                    # 10 characters per metre, up to 5 m
        warning = "   <-- OBSTACLE" if nearest_m < WARN_M else "               "
        print(f"\rahead: {nearest_m:5.2f} m  {bar:<50}{warning}", end="", flush=True)
except KeyboardInterrupt:
    print()
