"""LiDAR odometry for the robot: 2D scan matching (point-to-point ICP) of each STL-27L scan against a
keyframe, giving the robot's true motion (position, heading, speed) independent of wheel slip.

Robot frame: x forward, y left, angles counter-clockwise. The LiDAR's 0 deg points at robot angle
-(0 - FRONT) clockwise: its angles increase clockwise and the robot's front is at FRONT_DEG.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

FRONT_DEG = 271.5          # LiDAR angle of the robot's front (straight test legs, scan matching, 2026-11-04;
                           # the first forward probe said ~254)
SELF_MM = 150              # closer returns are the robot's own chassis
MAX_MM = 8000
GRID_M = 0.04              # voxel downsampling


def scan_to_points(scan):
    """[(angle_deg, dist_mm, intensity)] -> Nx2 array (m) in the robot frame, downsampled."""
    a = np.array([p[0] for p in scan], dtype=float)
    d = np.array([p[1] for p in scan], dtype=float)
    keep = (d > SELF_MM) & (d < MAX_MM)
    a, d = a[keep], d[keep] / 1000.0
    th = np.radians(FRONT_DEG - a)                     # clockwise LiDAR angle -> CCW robot angle
    pts = np.column_stack((d * np.cos(th), d * np.sin(th)))
    if len(pts) == 0:
        return pts
    key = np.floor(pts / GRID_M).astype(np.int64)      # one point per 4 cm cell
    _, idx = np.unique(key[:, 0] * 1_000_003 + key[:, 1], return_index=True)
    return pts[np.sort(idx)]


def transform(pts, x, y, th):
    c, s = math.cos(th), math.sin(th)
    return pts @ np.array([[c, s], [-s, c]]) + np.array([x, y])


def icp(ref_tree, ref_pts, cur, init=(0.0, 0.0, 0.0), iters=25, max_d=0.25):
    """Pose (x, y, th) of `cur`'s frame in `ref`'s frame. Returns (pose, rms m, inlier fraction)."""
    x, y, th = init
    rms, frac = float("inf"), 0.0
    gate = max_d
    for i in range(iters):
        p = transform(cur, x, y, th)
        d, j = ref_tree.query(p, distance_upper_bound=gate)
        ok = np.isfinite(d)
        if ok.sum() < 30:
            return (x, y, th), float("inf"), 0.0
        a, b = p[ok], ref_pts[j[ok]]
        ma, mb = a.mean(0), b.mean(0)
        h = (a - ma).T @ (b - mb)
        dth = math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
        c, s = math.cos(dth), math.sin(dth)
        r = np.array([[c, -s], [s, c]])
        t = mb - r @ ma
        # compose the increment onto the current estimate
        nx, ny = r @ np.array([x, y]) + t
        x, y, th = float(nx), float(ny), th + dth
        rms = float(np.sqrt((d[ok] ** 2).mean()))
        frac = ok.mean()
        gate = max(0.06, gate * 0.7)                   # tighten the correspondence gate as it converges
        if abs(dth) < 1e-4 and abs(t).max() < 1e-4:
            break
    return (x, y, th), rms, frac


class LidarOdom:
    """Feed scans in order with update(); keeps the robot's pose in the frame of the first scan."""

    def __init__(self, key_dist=0.25, key_angle=math.radians(12)):
        self.key = None            # (points, tree, pose of keyframe in world)
        self.pose = (0.0, 0.0, 0.0)
        self.rel = (0.0, 0.0, 0.0) # current pose relative to the keyframe
        self.key_dist, self.key_angle = key_dist, key_angle
        self.last_quality = (0.0, 1.0)

    def update(self, scan, guess_delta=None):
        """guess_delta: (dx, dy, dth) robot motion since the previous scan in the robot frame, or None.
        Returns (pose, ok)."""
        pts = scan_to_points(scan)
        if self.key is None:
            self.key = (pts, cKDTree(pts), self.pose)
            return self.pose, True
        init = self.rel
        if guess_delta is not None:                        # rel ∘ delta
            gx, gy, gt = guess_delta
            c, s = math.cos(self.rel[2]), math.sin(self.rel[2])
            init = (self.rel[0] + c * gx - s * gy, self.rel[1] + s * gx + c * gy, self.rel[2] + gt)
        rel, rms, frac = icp(self.key[1], self.key[0], pts, init)
        self.last_quality = (rms, frac)
        ok = rms < 0.08 and frac > 0.35
        if not ok:
            rel = init                                     # fall back to the guess for this scan
        self.rel = rel
        kx, ky, kt = self.key[2]
        c, s = math.cos(kt), math.sin(kt)
        self.pose = (kx + c * rel[0] - s * rel[1], ky + s * rel[0] + c * rel[1], kt + rel[2])
        if ok and (math.hypot(rel[0], rel[1]) > self.key_dist or abs(rel[2]) > self.key_angle):
            self.key = (pts, cKDTree(pts), self.pose)      # new keyframe
            self.rel = (0.0, 0.0, 0.0)
        return self.pose, ok
