#!/usr/bin/env python3
"""Find the robot's position AND heading by matching a LiDAR scan to OpenStreetMap building outlines.

    .venv/bin/python nav/map_localize.py [--buildings nav/buildings_bhee.json] [--scan nav/scan_here.json]
                                         [--lat LAT --lon LON] [--radius 25]

Near buildings RTK float can be off by ~8 m (7 Nov: it put the robot inside BHEE), and the heading from a short GPS
track by tens of degrees. Building walls seen by the LiDAR pin both down without GPS beyond a rough area:
- walls: the OSM building polygons (Overpass `way["building"] out geom`) rasterised into a 0.1 m grid, then a
  distance transform (metres to the nearest wall);
- scan: points in the robot frame (lidar_odom.scan_to_points: x forward, y left, LiDAR front 271.5 deg), several
  scans merged and thinned;
- search: every heading (2 deg steps) x every position within --radius of the rough estimate (0.5 m steps), score =
  mean of min(distance to wall, 0.5 m) over the points (trees, benches and people cost at most 0.5 m each), then a
  fine search around the best (0.1 m, 0.25 deg). The best score is compared with the best pose > 3 m or > 20 deg away:
  a clear gap means the answer is unambiguous.
Writes nav/robot_pose.json (lat, lon, heading) and nav/map_localize.png (scan drawn on the map at the found pose).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "motor_cal"))
sys.path.insert(0, HERE)
from lidar_odom import scan_to_points  # noqa: E402
from follow import Enu                  # noqa: E402

RES = 0.1                               # m per grid cell
CAP = 0.5                               # m, the most one point can cost


def wall_field(buildings, enu, half):
    """Distance (m) to the nearest building wall on a grid covering [-half, half] m around the origin."""
    n = int(2 * half / RES) + 1
    walls = np.zeros((n, n), bool)
    segs = []
    for e in buildings["elements"]:
        g = e.get("geometry")
        if not g:
            continue
        pts = [enu.to(p["lat"], p["lon"]) for p in g]
        for a, b in zip(pts, pts[1:]):
            segs.append((a, b))
            L = math.dist(a, b)
            for t in np.linspace(0, 1, max(2, int(L / (RES / 2)))):
                x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                i, j = int(round((y + half) / RES)), int(round((x + half) / RES))
                if 0 <= i < n and 0 <= j < n:
                    walls[i, j] = True
    dist = ndimage.distance_transform_edt(~walls) * RES
    return dist, segs


def score(dist, half, P, x, y, th):
    """Mean capped wall distance for robot-frame points P (N x 2) placed at pose (x, y, th). Lower is better."""
    c, s = math.cos(th), math.sin(th)
    X = P[:, 0] * c - P[:, 1] * s + x
    Y = P[:, 0] * s + P[:, 1] * c + y
    i = np.round((Y + half) / RES).astype(int)
    j = np.round((X + half) / RES).astype(int)
    n = dist.shape[0]
    ok = (i >= 0) & (i < n) & (j >= 0) & (j < n)
    d = np.full(len(P), CAP)
    d[ok] = np.minimum(dist[i[ok], j[ok]], CAP)
    return d.mean()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--buildings", default=os.path.join(HERE, "buildings_bhee.json"))
    ap.add_argument("--scan", default=os.path.join(HERE, "scan_here.json"))
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--radius", type=float, default=25.0, help="search this far (m) around the rough position")
    ap.add_argument("--max-range", type=float, default=30.0, help="ignore LiDAR returns beyond this (m)")
    a = ap.parse_args()
    if a.lat is None:
        p = json.load(open(os.path.join(HERE, "robot_position.json")))
        a.lat, a.lon = p["lat"], p["lon"]
    enu = Enu(a.lat, a.lon)
    half = a.radius + a.max_range + 5
    dist, segs = wall_field(json.load(open(a.buildings)), enu, half)

    scans = json.load(open(a.scan))
    P = np.vstack([scan_to_points(s) for s in scans])
    P = P[np.hypot(P[:, 0], P[:, 1]) < a.max_range]
    key = np.floor(P / 0.15).astype(np.int64)                         # thin to one point per 15 cm cell
    _, idx = np.unique(key[:, 0] * 1_000_003 + key[:, 1], return_index=True)
    P = P[idx]
    rng = np.random.default_rng(0)
    Pc = P[rng.choice(len(P), min(400, len(P)), replace=False)]       # coarse search on a subset
    print(f"{len(P)} scan points within {a.max_range:.0f} m ({len(Pc)} for the coarse search); "
          f"{len(segs)} wall segments; searching +-{a.radius:.0f} m, all headings", flush=True)

    # coarse: every 2 deg, every 0.5 m
    xs = np.arange(-a.radius, a.radius + 1e-9, 0.5)
    results = []
    n = dist.shape[0]
    for th in np.radians(np.arange(0, 360, 2)):
        c, s = math.cos(th), math.sin(th)
        X = Pc[:, 0] * c - Pc[:, 1] * s
        Y = Pc[:, 0] * s + Pc[:, 1] * c
        gx, gy = np.meshgrid(xs, xs, indexing="xy")
        tx, ty = gx.ravel()[:, None], gy.ravel()[:, None]
        i = np.clip(np.round((Y[None, :] + ty + half) / RES).astype(int), 0, n - 1)
        j = np.clip(np.round((X[None, :] + tx + half) / RES).astype(int), 0, n - 1)
        sc = np.minimum(dist[i, j], CAP).mean(1)
        k = sc.argmin()
        order = np.argsort(sc)[:30]
        for kk in order:
            results.append((sc[kk], tx[kk, 0], ty[kk, 0], th))
    results.sort()

    # fine: around the 5 best distinct coarse poses
    def refine(x0, y0, th0):
        best = (score(dist, half, P, x0, y0, th0), x0, y0, th0)
        for step_xy, step_th, span in ((0.25, math.radians(1.0), 3), (0.1, math.radians(0.25), 3)):
            x0, y0, th0 = best[1:]
            for th in th0 + step_th * np.arange(-span, span + 1):
                for x in x0 + step_xy * np.arange(-span, span + 1):
                    for y in y0 + step_xy * np.arange(-span, span + 1):
                        v = score(dist, half, P, x, y, th)
                        if v < best[0]:
                            best = (v, x, y, th)
        return best

    seeds = []
    for r in results:
        if all(math.dist(r[1:3], q[1:3]) > 2 or abs(math.remainder(r[3] - q[3], 2 * math.pi)) > math.radians(10) for q in seeds):
            seeds.append(r)
        if len(seeds) >= 6:
            break
    fine = sorted(refine(*q[1:]) for q in seeds)
    best = fine[0]
    rival = next((f for f in fine[1:] if math.dist(f[1:3], best[1:3]) > 3 or
                  abs(math.remainder(f[3] - best[3], 2 * math.pi)) > math.radians(20)), None)
    sc, x, y, th = best
    lat, lon = enu.back(x, y)
    hdg_enu = math.degrees(th)
    bearing = (90 - hdg_enu) % 360
    inl = np.mean(np.minimum(dist[np.clip(np.round((P[:, 0] * math.sin(th) + P[:, 1] * math.cos(th) + y + half) / RES).astype(int), 0, n - 1),
                                  np.clip(np.round((P[:, 0] * math.cos(th) - P[:, 1] * math.sin(th) + x + half) / RES).astype(int), 0, n - 1)], CAP) < 0.3)
    print(f"BEST: {lat:.7f}, {lon:.7f}  ({x:+.2f} m E, {y:+.2f} m N of the GPS estimate); heading {bearing:.1f} deg compass "
          f"({hdg_enu:.1f} deg from east CCW); mean capped wall distance {sc * 100:.1f} cm; {inl * 100:.0f}% of points within 30 cm of a wall")
    if rival:
        print(f"next-best different pose: score {rival[0] * 100:.1f} cm at ({rival[1]:+.1f}, {rival[2]:+.1f}) m, "
              f"heading {(90 - math.degrees(rival[3])) % 360:.0f} deg compass -> margin {(rival[0] - sc) * 100:.1f} cm "
              f"({'clear' if rival[0] - sc > 0.03 else 'AMBIGUOUS'})")
    json.dump(dict(lat=lat, lon=lon, heading_enu_deg=hdg_enu, bearing_deg=bearing, score_cm=sc * 100,
                   margin_cm=(rival[0] - sc) * 100 if rival else None, from_gps=[a.lat, a.lon]),
              open(os.path.join(HERE, "robot_pose.json"), "w"), indent=1)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 7))
    for (p, q) in segs:
        ax.plot([p[0], q[0]], [p[1], q[1]], "-", color="#52514e", lw=1)
    c, s = math.cos(th), math.sin(th)
    ax.plot(P[:, 0] * c - P[:, 1] * s + x, P[:, 0] * s + P[:, 1] * c + y, ".", ms=1.5, color="#d03b3b", label="LiDAR scan at the found pose")
    ax.plot([0], [0], "o", color="#fab219", ms=9, label="RTK float position")
    ax.annotate("", xy=(x + 3 * c, y + 3 * s), xytext=(x, y), arrowprops=dict(arrowstyle="->", color="#2a78d6", lw=2.5))
    ax.plot([x], [y], "o", color="#2a78d6", ms=9, label=f"found: heading {bearing:.0f} deg")
    ax.set_xlim(x - 35, x + 35); ax.set_ylim(y - 35, y + 35); ax.set_aspect("equal"); ax.grid(alpha=0.2)
    ax.legend(loc="upper right", fontsize=8); ax.set_xlabel("east, m"); ax.set_ylabel("north, m")
    ax.set_title("LiDAR scan matched to OSM building outlines (grey)")
    fig.savefig(os.path.join(HERE, "map_localize.png"), dpi=110, bbox_inches="tight")
    print("plot: nav/map_localize.png")


if __name__ == "__main__":
    main()
