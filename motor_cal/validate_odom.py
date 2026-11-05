import math, pickle, sys, time
sys.path.insert(0, "/home/sdteam22/motor_cal")
from lidar_odom import LidarOdom
import robot_drive as rd
d = pickle.load(open(sys.argv[1], "rb"))
scans, ticks = d["scans"], d["ticks"]
off = scans[0][0] - ticks[0]["t"]                 # scan clock -> tick clock (to ~0.1 s)
odo = LidarOdom()
poses, t_icp = [], []
for ts, s in scans:
    t0 = time.perf_counter(); p, ok = odo.update(s); t_icp.append(time.perf_counter() - t0)
    poses.append((ts - off, p, ok, odo.last_quality))
print(f"ICP: {len(scans)} scans, {sum(t_icp)/len(t_icp)*1000:.1f} ms avg, {max(t_icp)*1000:.0f} ms max; "
      f"{sum(1 for x in poses if not x[2])} scans rejected")
def pose_at(t):
    return min(poses, key=lambda x: abs(x[0] - t))[1]
print(f"{'leg':12s} {'gyro deg':>9s} {'lidar deg':>9s} | {'wheel m':>8s} {'lidar m':>8s}  slip")
for tag in dict.fromkeys(x["test"] for x in ticks):
    seg = [x for x in ticks if x["test"] == tag]
    a, b = seg[0], seg[-1]
    p0, p1 = pose_at(a["t"]), pose_at(b["t"] + 0.3)
    gy = b["yaw"] - a["yaw"]
    ly = math.degrees(p1[2] - p0[2])
    wheel = ((b["cl"] - a["cl"]) + (b["cr"] - a["cr"])) / 2 / rd.COUNTS_PER_REV * rd.WHEEL_C
    lid = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    print(f"{tag:12s} {gy:+9.1f} {ly:+9.1f} | {abs(wheel):8.2f} {lid:8.2f}  {(1 - lid / abs(wheel)) * 100 if wheel else 0:+5.0f}%")
