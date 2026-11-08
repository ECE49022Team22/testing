"""Local obstacle avoidance for follow.py: a rolling LiDAR costmap plus a grid planner (Dijkstra, through
scikit-image's MCP, or a pure-Python A* fallback) that bends the GPS route around things the map doesn't
know about: bins, bike racks, parked bikes, people.

Frames
  odom   wheels + gyro only, never nudged by GPS. The costmap lives here, so a GPS correction or jump can't
         smear it or move an obstacle relative to the robot.
  fused  follow.py's pose (ENU metres in route mode). The route lives here.
Each plan maps the route into odom with the current fused-vs-odom offset. A GPS correction then moves the
route relative to the obstacles, which is right, without moving the obstacles relative to the robot.

Per scan (about 10 Hz)  add_scan(scan, odom_pose)
    Log-odds update: +hit at each return, -miss along each beam, robot footprint forced free, positive
    cells slowly fade so people's trails and stale returns disappear.
Per plan (5 Hz)         plan(odom_pose, fused_pose, s_route)
    First: nothing within route_clear_m of the route ahead and the robot on it -> the plan is just the route
    (the usual case, ~1 ms). Otherwise a search on a 10 cm grid pooled from the 5 cm map (4x fewer cells);
    obstacle distances, smoothing and clearance checks stay at 5 cm. Distance transforms use OpenCV if present.
    cost = 1 + inflation (lethal inside lethal_m of an obstacle, quadratic out to inflate_m)
             + corridor (linear + 4th power in distance from the route, hard cap corridor_m)
             + kinematics (cells behind the robot or inside its 1 m turning circles: the search is
               holonomic, the robot can't reverse or pivot)
             + hysteresis beyond 1.5 m (keeps the side of an obstacle it chose, so it doesn't flip-flop)
    Goal: the best reachable point on the route 5-8.5 m ahead (prefers further along). The resulting path,
    in odom, is smoothed. No path inside the corridor -> blocked: stop and wait; still blocked after
    widen_after_s -> also try a 60 % wider corridor (a permanent barrier: go round it, over grass if need be).
Per control tick        target(odom_pose, lookahead(base))  pure-pursuit target on the local path (odom);
                                                            shorter look-ahead when squeezing past things
                        speed_limit(v)                      slower near obstacles and on tight curves
                        guard(scan, odom_pose, v)           stop / slow for returns on the planned path
                        recovery(scan, odom_pose, held_s)   back up 0.6 m if the guard holds it nose-up

Poses are (x, y, heading rad CCW). The robot frame is x forward, y left. Run this file for a timing
benchmark on the real BHEE scans in scan_here.json: python3 nav/local_nav.py. Design notes and the
simulation results: nav/LOCAL_NAV.md.
"""
import heapq
import math
import os
import sys
import threading
import time
from collections import deque
from itertools import chain

import numpy as np
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "motor_cal"))
try:
    from lidar_odom import FRONT_DEG, SELF_MM            # one source of truth for the LiDAR's mounting
except Exception:                                        # pragma: no cover
    FRONT_DEG, SELF_MM = 271.5, 150

try:
    from skimage.graph import MCP_Geometric
except ImportError:                                      # pip install scikit-image (aarch64 wheels exist)
    MCP_Geometric = None
try:
    import cv2                                           # already on the robot for the camera; ~8x faster EDT
except ImportError:                                      # pragma: no cover
    cv2 = None

# chassis rectangle about the turning centre, m: x back..front, y right..left (450 x 595 mm frame)
FOOTPRINT = (-0.30, 0.30, -0.23, 0.23)


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


_RAYS = (None, None)                                     # (last scan, its rays): map, guard and back-up share it


def scan_rays(scan):
    """Driver scan [(angle_deg, dist_mm, intensity)] -> (range m, ux, uy: unit vector, robot frame) of every
    return beyond SELF_MM. The driver already drops no-return beams. Remembers the last scan, because the map
    update, the guard and the back-up check all ask for the same one (5 times per scan)."""
    global _RAYS
    last, out = _RAYS                                    # one read: safe against the planner thread
    if last is scan:
        return out
    if isinstance(scan, np.ndarray):
        arr = scan.reshape(-1, 3)
    else:                                                # list of tuples: fromiter is 2x faster than asarray
        arr = np.fromiter(chain.from_iterable(scan), np.float64, 3 * len(scan)).reshape(-1, 3)
    d = arr[:, 1] / 1000.0
    keep = d > SELF_MM / 1000.0
    ang = np.radians(FRONT_DEG - arr[keep, 0])
    out = (d[keep], np.cos(ang), np.sin(ang))
    _RAYS = (scan, out)
    return out


def edt(free, res):
    """Distance (m) from every True cell to the nearest False one (exact Euclidean)."""
    if cv2 is not None:
        return cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * np.float32(res)
    return distance_transform_edt(free, sampling=res)


def pool2(a, op):
    """2 x 2 block reduce with a binary ufunc (a's sides must be even): the 10 cm search grid from the 5 cm map."""
    return op(op(a[0::2, 0::2], a[1::2, 0::2]), op(a[0::2, 1::2], a[1::2, 1::2]))


def resample(pts, step):
    """Polyline (N,2) -> points every `step` m along it, with their arc lengths."""
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return pts.copy(), np.zeros(len(pts))
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate(([0.0], np.cumsum(seg)))
    if s[-1] <= 0:
        return pts[:1].copy(), np.zeros(1)
    ss = np.arange(0.0, s[-1], step)
    ss = np.append(ss, s[-1]) if s[-1] - ss[-1] > 1e-6 else ss
    return np.column_stack((np.interp(ss, s, pts[:, 0]), np.interp(ss, s, pts[:, 1]))), ss


def to_robot(pts, pose):
    x, y, h = pose
    c, s = math.cos(h), math.sin(h)
    dx, dy = pts[:, 0] - x, pts[:, 1] - y
    return np.column_stack((c * dx + s * dy, -s * dx + c * dy))


def project(pts, s, x, y):
    """(arc length, distance) of the closest point to (x, y) on polyline pts with arc lengths s."""
    a, b = pts[:-1], pts[1:]
    d = b - a
    L2 = (d * d).sum(1)
    L2[L2 == 0] = 1e-12
    t = np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / L2, 0, 1)
    px, py = a[:, 0] + t * d[:, 0], a[:, 1] + t * d[:, 1]
    dist = np.hypot(px - x, py - y)
    i = int(dist.argmin())
    return float(s[i] + t[i] * (s[i + 1] - s[i])), float(dist[i])


def at_extended(pts, s, q):
    """Point at arc length q on the polyline; past the end it continues along the last segment."""
    if q <= s[-1]:
        return float(np.interp(q, s, pts[:, 0])), float(np.interp(q, s, pts[:, 1]))
    a, b = pts[-2], pts[-1]
    L = math.dist(a, b) or 1e-9
    k = (q - s[-1]) / L
    return float(b[0] + k * (b[0] - a[0])), float(b[1] + k * (b[1] - a[1]))


# ================================================================ costmap
class RollingCostmap:
    """Log-odds occupancy grid in the odom frame that follows the robot (re-centred by whole-cell shifts).
    Its centre sits `ahead_m` in front of the robot, because what's ahead matters more than what's behind."""

    def __init__(self, size_m=16.0, res=0.05, ahead_m=3.0, recenter_m=1.5, hit=0.85, miss=0.4,
                 l_min=-2.0, l_max=2.0, occ=0.6, fade=0.97, max_hit_m=8.0, max_free_m=6.0,
                 footprint=FOOTPRINT, lidar_xy=(0.0, 0.0)):
        self.n = int(round(size_m / res))
        self.res, self.size = res, self.n * res
        self.ahead, self.recenter_m = ahead_m, recenter_m
        self.hit, self.miss, self.l_min, self.l_max, self.occ, self.fade = hit, miss, l_min, l_max, occ, fade
        self.max_hit, self.max_free = max_hit_m, max_free_m
        self.fp, self.lidar_xy = footprint, lidar_xy
        self.L = np.zeros((self.n, self.n), np.float32)          # [row = y, col = x]
        self.x0 = self.y0 = None                                 # odom coords of cell (0, 0)'s corner
        self._hit = np.zeros(self.n * self.n, bool)
        self._free = np.zeros(self.n * self.n + 1, bool)         # last element: where off-grid samples go
        self._k = np.arange(int(max_free_m / res) + 1, dtype=np.float32) + 0.5   # ray samples, in cells
        fx = np.arange(footprint[0], footprint[1] + 1e-9, res / 2)
        fy = np.arange(footprint[2], footprint[3] + 1e-9, res / 2)
        gx, gy = np.meshgrid(fx, fy)
        self._fp_pts = np.column_stack((gx.ravel(), gy.ravel()))

    # ---- geometry
    def cell(self, x, y):
        """odom (x, y) arrays -> (row, col, inside-grid mask)."""
        c = np.floor((np.asarray(x) - self.x0) / self.res).astype(np.int64)
        r = np.floor((np.asarray(y) - self.y0) / self.res).astype(np.int64)
        ok = (c >= 0) & (c < self.n) & (r >= 0) & (r < self.n)
        return r, c, ok

    def xy(self, r, c):
        return self.x0 + (np.asarray(c) + 0.5) * self.res, self.y0 + (np.asarray(r) + 0.5) * self.res

    def _recenter(self, x, y, h):
        cx, cy = x + self.ahead * math.cos(h), y + self.ahead * math.sin(h)
        nx0 = math.floor((cx - self.size / 2) / self.res) * self.res
        ny0 = math.floor((cy - self.size / 2) / self.res) * self.res
        if self.x0 is None:
            self.x0, self.y0 = nx0, ny0
            return
        if math.hypot(cx - (self.x0 + self.size / 2), cy - (self.y0 + self.size / 2)) < self.recenter_m:
            return
        dc = int(round((nx0 - self.x0) / self.res))
        dr = int(round((ny0 - self.y0) / self.res))
        new = np.zeros_like(self.L)
        n = self.n
        if abs(dc) < n and abs(dr) < n:
            new[max(0, -dr):n - max(0, dr), max(0, -dc):n - max(0, dc)] = \
                self.L[max(0, dr):n - max(0, -dr), max(0, dc):n - max(0, -dc)]
        self.L = new
        self.x0 += dc * self.res
        self.y0 += dr * self.res

    def self_mask(self, px, py, pad=0.03):
        """Robot-frame points that fall on the chassis itself."""
        x0, x1, y0, y1 = self.fp
        return (px > x0 - pad) & (px < x1 + pad) & (py > y0 - pad) & (py < y1 + pad)

    # ---- update
    def update(self, scan, pose):
        x, y, h = pose
        self._recenter(x, y, h)
        d, ux, uy = scan_rays(scan)
        lx, ly = self.lidar_xy
        px, py = lx + d * ux, ly + d * uy                             # robot frame
        mine = self.self_mask(px, py)
        c, s = math.cos(h), math.sin(h)
        ox, oy = x + c * lx - s * ly, y + s * lx + c * ly             # LiDAR in odom
        ca, sa = c * ux - s * uy, s * ux + c * uy                     # beam directions in odom

        hit, free = self._hit, self._free
        hit[:] = False
        free[:] = False
        ok = ~mine & (d <= self.max_hit)
        r, cc, inside = self.cell(ox + d[ok] * ca[ok], oy + d[ok] * sa[ok])
        hit[r[inside] * self.n + cc[inside]] = True

        # free space: every 3rd beam (0.5 deg apart: about a cell at 6 m), one sample per cell, all beams at
        # once in grid units, each beam cut where it returns or leaves the grid; the rest land on a spare element
        k, n = self._k, self.n
        g0 = np.array([(ox - self.x0) / self.res, (oy - self.y0) / self.res])        # LiDAR, in cells
        u = np.column_stack((ca[::3], sa[::3]))
        with np.errstate(divide="ignore"):
            edge = np.where(u > 0, (n - g0) / u, np.where(u < 0, -g0 / u, np.inf)).min(1) - 0.5
        flen = np.minimum(np.where(mine, 0.0, np.minimum(d - self.res, self.max_free))[::3] / self.res, edge)
        gc = np.float32(g0[0]) + u[:, 0].astype(np.float32)[:, None] * k
        gr = np.float32(g0[1]) + u[:, 1].astype(np.float32)[:, None] * k
        free[np.where(k < flen[:, None], gr.astype(np.int32) * n + gc.astype(np.int32), n * n).ravel()] = True

        L = self.L.reshape(-1)
        np.multiply(L, self.fade, out=L, where=L > 0)                 # unconfirmed returns fade (~6 s)
        f = free[:-1] & ~hit
        L[f] = np.maximum(L[f] - self.miss, self.l_min)
        L[hit] = np.minimum(L[hit] + self.hit, self.l_max)
        self.clear_footprint(pose)

    def clear_footprint(self, pose):
        x, y, h = pose
        c, s = math.cos(h), math.sin(h)
        p = self._fp_pts
        r, cc, ok = self.cell(x + c * p[:, 0] - s * p[:, 1], y + s * p[:, 0] + c * p[:, 1])
        self.L[r[ok], cc[ok]] = self.l_min

    def occupied(self):
        return self.L > self.occ


# ================================================================ planner
class LocalNav:
    def __init__(self, lethal_m=0.30, inflate_m=1.0, w_inflate=12.0, corridor_m=1.5, w_corridor=2.0,
                 w_corridor_lin=1.0, carrot_m=7.0, w_prev=0.4, prev_skip_m=1.5, route_clear_m=0.6,
                 route_snap_m=0.35, progress_bonus=1.2, replan_s=0.2,
                 widen_after_s=8.0, widen=1.6, a_lat=0.5, clear_slow=(0.35, 0.90), v_min_scale=0.35,
                 min_radius=1.0, w_kin=20.0, use_mcp=True, **map_kw):
        self.map = RollingCostmap(**map_kw)
        self.lethal, self.inflate, self.w_inflate = lethal_m, inflate_m, w_inflate
        self.corridor, self.w_corridor, self.carrot = corridor_m, w_corridor, carrot_m
        self.w_corridor_lin, self.prev_skip, self.route_clear, self.route_snap = \
            w_corridor_lin, prev_skip_m, route_clear_m, route_snap_m
        self.w_prev, self.bonus = w_prev, progress_bonus
        self.widen_after, self.widen = widen_after_s, widen
        self.min_radius, self.w_kin = min_radius, w_kin
        self.blocked_since = None                                # blocked this long -> try a wider corridor
        self._back = None                                        # odom (x, y) where a back-up started
        self.replan_s, self.a_lat, self.clear_slow, self.v_min_scale = replan_s, a_lat, clear_slow, v_min_scale
        self.use_mcp = use_mcp and MCP_Geometric is not None
        self.route = self.route_s = None
        # (local path in odom, its arc lengths, plan result): swapped as one tuple, so the control loop never
        # sees a path from one plan with the arc lengths of another while the planner thread replaces it
        self.cur = (None, None, {"ok": False, "why": "no plan yet", "v_scale": 0.0})
        self.t_plan = -1e9
        self.lock = threading.Lock()
        self.stats = {"scan_ms": deque(maxlen=5000), "plan_ms": deque(maxlen=5000)}

    @property
    def path(self):
        return self.cur[0]

    @property
    def path_s(self):
        return self.cur[1]

    @property
    def result(self):
        return self.cur[2]

    def set_route(self, pts):
        with self.lock:
            self.route, self.route_s = resample(pts, 0.1)

    def cancel_recovery(self):
        self._back = None

    def add_scan(self, scan, odom_pose):
        t0 = time.perf_counter()
        with self.lock:
            self.map.update(scan, odom_pose)
        self.stats["scan_ms"].append((time.perf_counter() - t0) * 1e3)

    # ---- the plan
    def due(self, now):
        return now - self.t_plan >= self.replan_s

    def plan(self, odom_pose, fused_pose, s_route, now=None):
        t0 = time.perf_counter()
        self.t_plan = now = time.monotonic() if now is None else now
        wide = self.blocked_since is not None and now - self.blocked_since >= self.widen_after
        with self.lock:
            res = self._plan(odom_pose, fused_pose, s_route, wide)
        if not res["ok"]:
            self.blocked_since = now if self.blocked_since is None else self.blocked_since
            if not wide and self.widen_after > 0:
                res["why"] += f" (waiting; a wider corridor after {self.widen_after:g} s)"
        elif res.get("cap", self.corridor) <= self.corridor:
            self.blocked_since = None                            # back inside the normal corridor
        res["ms"] = (time.perf_counter() - t0) * 1e3
        self.stats["plan_ms"].append(res["ms"])
        self.cur = (res["path"], res["path_s"], res) if res["ok"] else (None, None, res)
        return res

    def _route_window(self, odom_pose, fused_pose, s_route):
        lo, hi = s_route - 1.0, s_route + self.carrot + 2.0                # nothing is planned behind it
        m = (self.route_s >= lo) & (self.route_s <= hi)
        if m.sum() < 2:
            m = np.zeros_like(m)
            m[-2:] = True
        pts, ss = self.route[m], self.route_s[m]
        ox, oy, oh = odom_pose
        fx, fy, fh = fused_pose
        d = wrap(oh - fh)
        c, s = math.cos(d), math.sin(d)
        dx, dy = pts[:, 0] - fx, pts[:, 1] - fy
        return np.column_stack((ox + c * dx - s * dy, oy + s * dx + c * dy)), ss

    def _plan(self, odom_pose, fused_pose, s_route, wide=False):
        M, res = self.map, self.map.res
        if self.route is None or M.x0 is None:
            return {"ok": False, "why": "no route or no scans yet", "v_scale": 0.0}
        rpts, rs = self._route_window(odom_pose, fused_pose, s_route)
        x, y, h = odom_pose
        for cap in ((self.corridor, self.corridor * self.widen) if wide else (self.corridor,)):
            box = self._crop(rpts, x, y, cap)
            if box is None:
                return {"ok": False, "why": "route is outside the map", "v_scale": 0.0}
            r0, r1, c0, c1 = box
            occ = M.L[r0:r1, c0:c1] > M.occ
            d_obs = edt(~occ, res) if occ.any() else np.full(occ.shape, 99.0, np.float32)
            if cap == self.corridor:
                out = self._route_plan(rpts, rs, x, y, d_obs, r0, c0)   # cheap, and the usual case
                if out is not None:
                    return out
            cost, start = self._costs(rpts, odom_pose, occ, d_obs, r0, c0, cap)
            if isinstance(start, str):
                return {"ok": False, "why": start, "v_scale": 0.0}
            out = self._best_path(cost, start, rpts, rs, s_route, x, y, d_obs, r0, c0)
            if out is not None:
                out.update(why="" if cap == self.corridor else "corridor widened", cap=cap, crop=box)
                return out
        return {"ok": False, "why": "path blocked", "v_scale": 0.0}

    def _crop(self, rpts, x, y, cap):
        """Map rows / cols around the route window and the robot, padded by the corridor and the inflation, with
        even sides (for the 10 cm search grid). None if that is off the map."""
        M, res, pad = self.map, self.map.res, cap + self.inflate + 0.2
        c0 = max(0, int((min(rpts[:, 0].min(), x) - pad - M.x0) / res))
        c1 = min(M.n, int((max(rpts[:, 0].max(), x) + pad - M.x0) / res) + 1)
        r0 = max(0, int((min(rpts[:, 1].min(), y) - pad - M.y0) / res))
        r1 = min(M.n, int((max(rpts[:, 1].max(), y) + pad - M.y0) / res) + 1)
        c1, r1 = c1 - (c1 - c0) % 2, r1 - (r1 - r0) % 2
        return (r0, r1, c0, c1) if c1 - c0 >= 4 and r1 - r0 >= 4 else None

    def _cells(self, pts, r0, c0, shape, f=1):
        """odom points -> (rows, cols) of those inside a crop at (r0, c0) of `shape` (f = 2: the 10 cm grid), and
        which points those were."""
        r, c, _ = self.map.cell(pts[:, 0], pts[:, 1])
        r, c = (r - r0) // f, (c - c0) // f
        ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
        return r[ok], c[ok], ok

    def _route_plan(self, rpts, rs, x, y, d_obs, r0, c0):
        """The route itself as the plan, if the robot is on it and nothing is within route_clear_m of it ahead
        (no planner wiggle on a clear walk). None otherwise."""
        q0, dq = project(rpts, rs, x, y)
        ahead = (rs >= q0 - 0.2) & (rs <= min(q0 + self.carrot + 1.0, self.route_s[-1]))
        r, c, ok = self._cells(rpts[ahead], r0, c0, d_obs.shape)
        if dq > self.route_snap or not ok.size or not ok.all() or d_obs[r, c].min() <= self.route_clear:
            return None
        m = rs >= q0
        path, ps = resample(np.vstack(([[*at_extended(rpts, rs, q0)]], rpts[m])), 0.1)
        v_scale, clear, kmax = self._speed(path, ps, d_obs, r0, c0)
        return {"ok": True, "why": "", "path": path, "path_s": ps, "goal_s": float(rs[m][-1]), "v_scale": v_scale,
                "clearance": clear, "kappa": kmax, "deviation": dq, "cap": self.corridor, "on_route": True}

    def _costs(self, rpts, pose, occ, d_obs, r0, c0, cap):
        """Cost of each cell of the 10 cm search grid (inf = no-go) and the robot's cell in it (or why not).
        No-go uses the mean of a 10 cm cell's four 5 cm obstacle distances (its centre's, within 3.5 cm), so every
        gap of 0.7 m or more stays open. The inflation cost uses the best of the four, as a 5 cm path could pick
        it: with the mean, a narrow gap looked ~20 % dearer and the search went round things instead."""
        x, y, h = pose
        g = 2 * self.map.res
        d, d_best = pool2(d_obs, np.add) * 0.25, pool2(d_obs, np.maximum)
        sr, sc, ok = self._cells(np.array([[x, y]]), r0, c0, d.shape, 2)
        if not ok[0]:
            return None, "robot is outside the map"
        sr, sc = int(sr[0]), int(sc[0])
        on = np.zeros(occ.shape, bool)                             # at 5 cm, like the obstacles: the corridor
        rr, rc, _ = self._cells(resample(rpts, g / 4)[0], r0, c0, occ.shape)   # edge mustn't move outwards
        on[rr, rc] = True
        d_route = pool2(edt(~on, g / 2), np.add) * 0.25 if on.any() else np.full(d.shape, 99.0, np.float32)
        cap_eff = max(cap, d_route[sr, sc] + 0.5)                  # always allowed to come back
        # corridor: linear (so the plan pulls back onto the route) plus a term that is steep near the corridor's
        # edge (~ the walk's edge) and flat past it (where the robot may be, after a detour): with a square,
        # going round the bench beside a 1.0 m gap, on the grass, cost within 1 % of going through the gap
        cost = 1.0 + self.w_corridor_lin * d_route + self.w_corridor * (np.minimum(d_route, cap) / cap) ** 4
        soft = np.clip((self.inflate - d_best) / (self.inflate - self.lethal), 0.0, 1.0)
        cost += self.w_inflate * soft * soft
        yy, xx = np.ogrid[:d.shape[0], :d.shape[1]]
        dx, dy = (xx - sc) * g, (yy - sr) * g
        if self.w_prev and self.path is not None and len(self.path) >= 2:
            # hysteresis only beyond prev_skip_m: it keeps the chosen side of an obstacle, but near the robot it
            # would just copy the last plan and let the robot wander
            q, _ = project(self.path, self.path_s, x, y)
            pp = self.path[self.path_s >= q + self.prev_skip]
            pr, pc, _ = self._cells(resample(pp, g / 2)[0], r0, c0, d.shape, 2) if len(pp) >= 2 else ([], [], 0)
            if len(pr):
                onp = np.zeros(d.shape, bool)
                onp[pr, pc] = True
                cost += self.w_prev * (dx * dx + dy * dy > self.prev_skip ** 2) * np.minimum(edt(~onp, g), 0.6)
        if self.w_kin:
            # the grid search is holonomic, the robot isn't: no reversing, nothing tighter than min_radius. Make
            # cells behind it and inside its two tightest turning circles expensive (not forbidden, so a dead end
            # still gives a plan and the guard + back-up deal with it)
            fwd = dx * math.cos(h) + dy * math.sin(h)
            lat = -dx * math.sin(h) + dy * math.cos(h)
            R = self.min_radius
            rear = (fwd < -0.1) & (dx * dx + dy * dy < 1.5 ** 2)
            turn = ((lat - R) ** 2 + fwd ** 2 < (0.9 * R) ** 2) | ((lat + R) ** 2 + fwd ** 2 < (0.9 * R) ** 2)
            cost += self.w_kin * (rear | turn)
        cost[d <= self.lethal] = np.inf
        cost[d_route > cap_eff] = np.inf
        if not np.isfinite(cost[sr, sc]):            # inflation covers the robot: let it drive out, never through
            esc = (dx * dx + dy * dy <= (self.lethal + g) ** 2) & ~np.isfinite(cost) & ~pool2(occ, np.logical_or)
            cost[esc & (d_route <= cap_eff + 1.0)] = 1.0 + self.w_inflate + 5.0
        return cost, (sr, sc) if np.isfinite(cost[sr, sc]) else "robot is on an obstacle cell"

    def _best_path(self, cost, start, rpts, rs, s_route, x, y, d_obs, r0, c0):
        """Cheapest path to the best goal on the route 5-8.5 m ahead (cost minus progress_bonus per metre along
        the route), smoothed, or None if blocked. Closer goals only when those are past the route's end or off
        the map: aiming short of a blockage just drives the robot up to it, where its 1 m turning radius can't
        get it out again."""
        g, end_s = 2 * self.map.res, self.route_s[-1]
        for lo, hi, near in ((s_route + self.carrot - 2.0, s_route + self.carrot + 1.5, False),
                             (s_route + 1.0, s_route + self.carrot - 2.0, True)):
            hi = min(hi, end_s)
            if hi < lo and end_s > s_route:
                lo = hi = end_s
            qs = np.unique(np.append(np.arange(lo, hi + 1e-9, 0.25), hi)) if hi >= lo else np.array([])
            qs = qs[(qs >= rs[0]) & (qs <= rs[-1])]
            pts = np.column_stack((np.interp(qs, rs, rpts[:, 0]), np.interp(qs, rs, rpts[:, 1])))
            gr, gc, gok = self._cells(pts, r0, c0, cost.shape, 2)
            fin = np.isfinite(cost[gr, gc])
            if not fin.any():
                if gok.any() and not near:
                    return None                                     # far goals are on the map but blocked
                continue
            cells, qok = list(zip(gr[fin].tolist(), gc[fin].tolist())), qs[gok][fin]
            cum, trace = self._search(cost, start, cells)
            vals = np.array([cum[r, c] for r, c in cells])
            if not np.isfinite(vals).any():
                if not near:
                    return None
                continue
            j = int(np.where(np.isfinite(vals), vals * g - self.bonus * (qok - s_route), np.inf).argmin())
            cp = np.array(trace(cells[j]))
            raw = np.column_stack(self.map.xy(r0 + 2 * cp[:, 0] + 0.5, c0 + 2 * cp[:, 1] + 0.5))
            raw[0] = (x, y)
            path, ps = self._smooth(raw, d_obs, r0, c0)
            v_scale, clear, kmax = self._speed(path, ps, d_obs, r0, c0)
            return {"ok": True, "path": path, "path_s": ps, "goal_s": float(qok[j]), "v_scale": v_scale,
                    "clearance": clear, "kappa": kmax, "deviation": self._deviation(path, rpts)}
        return None

    def _search(self, cost, start, ends):
        if self.use_mcp:
            m = MCP_Geometric(cost, fully_connected=True)
            cum, _ = m.find_costs([start], ends, find_all_ends=True)
            return cum, m.traceback
        return _astar_all(cost, start, ends)

    def _smooth(self, raw, d_obs, r0, c0):
        M = self.map
        path, s = resample(raw, 0.1)
        if len(path) >= 7:
            sm = path.copy()
            k = 3
            for _ in range(2):
                pad = np.concatenate((np.repeat(sm[:1], k, 0), sm, np.repeat(sm[-1:], k, 0)))
                cs = np.cumsum(np.vstack((np.zeros((1, 2)), pad)), axis=0)
                sm = (cs[2 * k + 1:] - cs[:-2 * k - 1]) / (2 * k + 1)
                sm[0], sm[-1] = path[0], path[-1]
            if self._clear_along(sm, d_obs, r0, c0) > self.lethal:
                path, s = resample(sm, 0.1)
        return path, s

    def _clear_along(self, pts, d_obs, r0, c0):
        r, c, ok = self.map.cell(pts[:, 0], pts[:, 1])
        r, c = r - r0, c - c0
        ok &= (r >= 0) & (r < d_obs.shape[0]) & (c >= 0) & (c < d_obs.shape[1])
        return float(d_obs[r[ok], c[ok]].min()) if ok.any() else 99.0

    def _speed(self, path, s, d_obs, r0, c0):
        near = path[s <= 2.5]
        clear = self._clear_along(near[1:] if len(near) > 1 else near, d_obs, r0, c0)
        lo, hi = self.clear_slow
        v_scale = float(np.clip((clear - lo) / (hi - lo), self.v_min_scale, 1.0))
        kmax = 0.0
        p = path[s <= 3.0]
        if len(p) >= 5:
            hdg = np.unwrap(np.arctan2(np.diff(p[:, 1]), np.diff(p[:, 0])))
            k = np.abs(np.convolve(np.diff(hdg) / 0.1, np.ones(5) / 5, mode="valid"))
            kmax = float(k.max()) if len(k) else 0.0
        return v_scale, clear, kmax

    @staticmethod
    def _deviation(path, rpts):
        """Largest distance (m) of the local path from the route: how far it bends around things."""
        p = path[::3]
        d = np.hypot(p[:, None, 0] - rpts[None, :, 0], p[:, None, 1] - rpts[None, :, 1]).min(1)
        return float(d.max())

    # ---- helpers for the control loop
    def speed_limit(self, v):
        """Speed for this tick: v scaled by clearance along the path and capped by its curvature."""
        r = self.result
        if not r.get("ok"):
            return 0.0
        v = v * r["v_scale"]
        if r.get("kappa", 0) > 1e-3:
            v = min(v, math.sqrt(self.a_lat / r["kappa"]))
        return v

    def lookahead(self, base, lo=0.8, full_clear=0.9):
        """Pure-pursuit look-ahead for this tick: shorter when the path squeezes past something, so the
        robot cuts its corners less (a 1.5 m look-ahead cuts a tight bump by ~0.1 m)."""
        c = self.result.get("clearance")
        if not self.result.get("ok") or c is None or self.result.get("on_route"):
            return base
        return float(np.clip(base * c / full_clear, lo, base))

    def target(self, odom_pose, lookahead):
        """Pure-pursuit target (odom frame) on the local path, or None if there's no path."""
        p, s, _ = self.cur
        if p is None or len(p) < 2:
            return None
        q, _ = project(p, s, odom_pose[0], odom_pose[1])
        return at_extended(p, s, q + lookahead)

    def recovery(self, scan, odom_pose, held_s, after_s=2.5, back_m=0.6, v_back=0.15, rear_m=0.45):
        """Back straight up when the guard has held the robot for after_s although there is a plan: it is
        nose-up to something and can't turn tighter than its minimum radius. Returns a reverse speed (m/s,
        negative) to drive both wheels at, or 0.0 to carry on normally. Stops backing after back_m or as
        soon as anything is within rear_m behind the chassis."""
        d, ux, uy = scan_rays(scan)
        lx, ly = self.map.lidar_xy
        px, py = lx + d * ux, ly + d * uy
        keep = ~self.map.self_mask(px, py)
        back = self.map.fp[0]
        rear_clear = not ((px[keep] < back) & (px[keep] > back - rear_m) & (np.abs(py[keep]) < 0.30)).any()
        if self._back is not None:
            if math.dist(self._back, odom_pose[:2]) >= back_m or not rear_clear:
                self._back = None
                return 0.0
            return -v_back
        if held_s >= after_s and self.path is not None and rear_clear:
            self._back = tuple(odom_pose[:2])
            return -v_back
        return 0.0

    def guard(self, scan, odom_pose, v=0.0, stop_m=0.8, slow_m=2.0, stop_w=0.28, slow_w=0.40,
              dead_s=0.8, box_w=0.26, near_m=0.05):
        """(speed factor 0 / 0.5 / 1, reason). Looks along the planned path instead of a straight box,
        plus a short straight box for the distance the robot covers before a turn takes effect, plus a ring
        near_m around the chassis outline (returns inside the outline are the robot itself)."""
        d, ux, uy = scan_rays(scan)
        lx, ly = self.map.lidar_xy
        px, py = lx + d * ux, ly + d * uy
        keep = ~self.map.self_mask(px, py, pad=0.01) & (d < 8.0)
        px, py = px[keep], py[keep]
        if len(px) == 0:
            return 1.0, ""
        stop_m = max(stop_m, 0.3 + 1.2 * v)                      # ~0.5 s of wheel lag to stop, plus margin
        slow_m = max(slow_m, 3.0 * v)
        fp = self.map.fp
        ex = np.maximum(np.maximum(fp[0] - px, px - fp[1]), 0.0)
        ey = np.maximum(np.maximum(fp[2] - py, py - fp[3]), 0.0)
        ring = np.hypot(ex, ey)
        if (ring < near_m).any():
            i = int(ring.argmin())
            return 0.0, f"something {ring[i]:.2f} m from the chassis at {math.degrees(math.atan2(py[i], px[i])):+.0f} deg"
        box_l = max(0.45, v * dead_s + 0.35) + self.map.fp[1]
        inbox = (px > 0) & (px < box_l) & (np.abs(py) < box_w)
        if inbox.any():
            return 0.0, f"obstacle {px[inbox].min():.2f} m dead ahead"
        path, path_s, _ = self.cur
        if path is None:                                         # no plan: the old straight corridor
            ahead = (px > 0) & (np.abs(py) < 0.45)
            if ahead.any():
                dmin = px[ahead].min()
                if dmin < stop_m + self.map.fp[1]:
                    return 0.0, f"obstacle {dmin:.2f} m ahead"
                if dmin < slow_m + self.map.fp[1]:
                    return 0.5, f"slowing: obstacle {dmin:.2f} m ahead"
            return 1.0, ""
        q, _ = project(path, path_s, odom_pose[0], odom_pose[1])
        m = (path_s >= q) & (path_s <= q + slow_m + 0.3)
        seg = path[m]
        if len(seg) < 2:
            return 1.0, ""
        rp = np.vstack(([[0.0, 0.0]], to_robot(seg, odom_pose)))   # the plan from the robot, robot frame
        lo, hi = rp.min(0) - slow_w, rp.max(0) + slow_w
        near = (px > lo[0]) & (px < hi[0]) & (py > lo[1]) & (py < hi[1])   # only returns that could be close
        if not near.any():
            return 1.0, ""
        qx, qy = px[near][:, None], py[near][:, None]
        a, ab = rp[:-1], np.diff(rp, axis=0)                           # distance to each segment of the plan
        L = np.maximum(np.hypot(ab[:, 0], ab[:, 1]), 1e-9)
        t = np.clip(((qx - a[:, 0]) * ab[:, 0] + (qy - a[:, 1]) * ab[:, 1]) / (L * L), 0.0, 1.0)
        dd = np.hypot(qx - a[:, 0] - t * ab[:, 0], qy - a[:, 1] - t * ab[:, 1])
        j, i = dd.argmin(1), np.arange(len(qx))
        dist, along = dd[i, j], np.concatenate(([0.0], np.cumsum(L)))[j] + t[i, j] * L[j]
        front = self.map.fp[1]
        stop = (dist < stop_w) & (along < stop_m + front) & (along > 0.05)
        if stop.any():
            return 0.0, f"obstacle on the path {along[stop].min():.2f} m ahead"
        slow = (dist < slow_w) & (along < slow_m + front)
        if slow.any():
            return 0.5, f"slowing: obstacle near the path {along[slow].min():.2f} m ahead"
        return 1.0, ""


# ================================================================ fallback search (no scikit-image)
def _astar_all(cost, start, ends):
    """Dijkstra from start until every reachable end is settled (same contract as MCP: cum cost in cells)."""
    R, C = cost.shape
    cum = np.full(cost.shape, np.inf)
    prev = -np.ones(cost.shape, np.int64)
    left = set(ends)
    cum[start] = 0.0
    pq = [(0.0, start)]
    moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
    cl = cost.tolist()
    cu = cum                                   # numpy for the result, but look-ups in Python lists below
    best = {start: 0.0}
    while pq and left:
        g, (r, c) = heapq.heappop(pq)
        if g > best.get((r, c), math.inf):
            continue
        left.discard((r, c))
        cr = cl[r][c]
        for dr, dc, w in moves:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C:
                cn = cl[nr][nc]
                if cn == math.inf:
                    continue
                ng = g + w * 0.5 * (cr + cn)
                if ng < best.get((nr, nc), math.inf):
                    best[(nr, nc)] = ng
                    prev[nr, nc] = r * C + c
                    heapq.heappush(pq, (ng, (nr, nc)))
    for (r, c), g in best.items():
        cu[r, c] = g

    def trace(end):
        out = [end]
        k = prev[end]
        while k >= 0:
            out.append((int(k // C), int(k % C)))
            k = prev[out[-1]]
        return out[::-1]
    return cu, trace


# ================================================================ background thread for follow.py
class NavThread(threading.Thread):
    """Runs the map update on every new scan and a plan every replan_s, off the 20 Hz control loop.
    pose_fn() returns (odom_pose, fused_pose, s_route): fused_pose / s_route may be None (no route yet: the
    map is still built, nothing is planned), or the whole thing None (not ready). With log=True it keeps
    every scan with its poses for save_scans() (for replaying a real run through the planner offline)."""

    def __init__(self, nav, lid, pose_fn, log=False):
        super().__init__(daemon=True)
        self.nav, self.lid, self.pose_fn = nav, lid, pose_fn
        self.stop = threading.Event()
        self.last_t = 0.0
        self.error = None
        self.log = [] if log else None

    def run(self):
        while not self.stop.is_set():
            t, scan = self.lid.t, self.lid.scan
            if scan is None or t == self.last_t:
                time.sleep(0.005)
                continue
            self.last_t = t
            p = self.pose_fn()
            if p is None or p[0] is None:
                continue
            odom, fused, s_route = p
            try:
                self.nav.add_scan(scan, odom)
                if fused is not None and s_route is not None and self.nav.due(time.monotonic()):
                    self.nav.plan(odom, fused, s_route)
            except Exception as e:                               # the planner must never kill the control loop
                self.error = repr(e)
                self.nav.cur = (None, None, {"ok": False, "why": f"planner error {e!r}", "v_scale": 0.0})
            if self.log is not None:
                arr = np.asarray(scan, dtype=np.float64).reshape(-1, 3)
                self.log.append((t, odom, fused, s_route, (arr[:, 0] * 100).astype(np.int32),
                                 arr[:, 1].astype(np.int32)))

    def save_scans(self, path):
        """Write the logged scans as .npz: t, odom (N,3), fused (N,3, NaN before the route), s, and the scans
        concatenated (angle in 0.01 deg, dist mm) with per-scan offsets."""
        if not self.log:
            return None
        L = self.log
        nan3 = (math.nan, math.nan, math.nan)
        lens = np.array([len(e[4]) for e in L])
        np.savez_compressed(path, t=np.array([e[0] for e in L]), odom=np.array([e[1] for e in L]),
                            fused=np.array([e[2] if e[2] is not None else nan3 for e in L]),
                            s=np.array([e[3] if e[3] is not None else math.nan for e in L]),
                            offsets=np.concatenate(([0], np.cumsum(lens))),
                            angle_cdeg=np.concatenate([e[4] for e in L]), dist_mm=np.concatenate([e[5] for e in L]))
        return path


def load_scans(path):
    """Inverse of NavThread.save_scans: list of (t, odom, fused or None, s or None, scan)."""
    z = np.load(path)
    out = []
    for i in range(len(z["t"])):
        a, b = z["offsets"][i], z["offsets"][i + 1]
        scan = np.column_stack((z["angle_cdeg"][a:b] / 100.0, z["dist_mm"][a:b], np.full(b - a, 100.0)))
        f = z["fused"][i]
        out.append((float(z["t"][i]), tuple(z["odom"][i]), None if np.isnan(f[0]) else tuple(f),
                    None if np.isnan(z["s"][i]) else float(z["s"][i]), scan))
    return out


# ================================================================ benchmark on the real BHEE scans
if __name__ == "__main__":
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    scans = json.load(open(os.path.join(here, "scan_here.json")))
    print(f"scikit-image MCP: {'yes' if MCP_Geometric is not None else 'NO (pip install scikit-image; using the slow pure-Python search)'}; "
          f"{len(scans)} real scans of {np.mean([len(s) for s in scans]):.0f} points (BHEE entrance)")
    pose = (0.0, 0.0, 0.0)
    for use_mcp in ((True, False) if MCP_Geometric is not None else (False,)):
        for hd, what in ((0, "clear route (plan = the route)"), (90, "route through the bike racks (full search)")):
            nav = LocalNav(use_mcp=use_mcp)
            h = math.radians(hd)
            nav.set_route([(0.0, 0.0), (12.0 * math.cos(h), 12.0 * math.sin(h))])
            for i in range(30):
                nav.add_scan(scans[i % len(scans)], pose)
            t, r = [], None
            for i in range(20):
                nav.add_scan(scans[i % len(scans)], pose)
                nav.t_plan = -1e9
                r = nav.plan(pose, pose, 0.0)
                t.append(r["ms"])
            sm = np.array(nav.stats["scan_ms"])[30:]
            print(f"{'MCP' if use_mcp else 'pure-Python'} | {what}: map update median {np.median(sm):.1f} ms "
                  f"(max {sm.max():.1f}), plan median {np.median(t):.1f} ms (max {max(t):.1f}) | ok={r['ok']} "
                  f"clearance {r.get('clearance', float('nan')):.2f} m, bends {r.get('deviation', float('nan')):.2f} m")
    print("Budget: a scan every 100 ms and a plan every 200 ms, in their own thread (NavThread).")
