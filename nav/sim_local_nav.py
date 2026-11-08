"""Closed-loop simulator for local_nav.py: follow.py's controller, the robot's measured turning lag, a
simulated STL27L, and campus-like obstacles. It runs everything the robot would run (map update, plan,
path-aware guard, pure pursuit, yaw-rate PI), so a planner change can be checked here before the Pi.

  python3 nav/sim_local_nav.py                       # every scenario x model x speed -> sim_results.json
  python3 nav/sim_local_nav.py trash_can --model taped --speed 0.6 --plot can.png
  python3 nav/sim_local_nav.py trash_can --baseline  # today's follow.py: route pursuit + straight guard

Robot models (fitted to the 7 Nov run toward Lambertus, taped passive wheels, 0.3 m/s):
  taped    wheel loop 0.3 s dead + 0.25 s lag, then 0.35 s more yaw dead time + 0.1 s lag and stick-slip
           (no turn at all below a break-away angle that grows at low speed, then a snap). Total yaw delay
           ~1 s, a bit worse than the fitted 0.8 + 0.1 s.
  casters  the wheel loop only (yaw follows the wheels), no stick-slip: what swivel casters should give.
LiDAR: 2160 beams per 0.1 s sweep, cast from the pose at each beam's time (so turning skews the scan as on
the robot), 12 mm noise, 2 % dropouts, returns past 25 m dropped, the mast's 30 mm returns and an
intermittent 0.18 m self-return at +52 deg. Grass edges are invisible to it (only the route keeps the robot
on the sidewalk). Fused pose = truth + a few cm of RTK wander; odom = wheels (2 % scale error) + gyro
(0.15 deg/s bias).
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import local_nav as ln  # noqa: E402

WHEEL_C = math.pi * 0.2032
WHEEL_SCALE = 0.94
TRACK_EFF = 0.95
FP = ln.FOOTPRINT
DT = 0.01
SELF_RETURN_P = 0.2                                          # share of scans with the 0.18 m self-return


# ================================================================ world
class World:
    def __init__(self, center, half_w=1.5, circles=(), segs=(), peds=(), route_offset=0.0, name=""):
        self.name = name
        self.center = np.array(center, float)                    # sidewalk centre line
        self.half_w = half_w
        self.circles = np.array(circles, float).reshape(-1, 3)
        self.segs = np.array(segs, float).reshape(-1, 4)
        self.peds = list(peds)                                   # functions t -> [(x, y, r), ...]
        self.route = offset_polyline(self.center, route_offset)
        self.n_fg = (len(self.circles), len(self.segs))           # foreground (scenario) obstacles
        self._background()
        pts = [self.circles]
        for x1, y1, x2, y2 in self.segs:
            n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.02) + 1)
            pts.append(np.column_stack((np.linspace(x1, x2, n), np.linspace(y1, y2, n), np.zeros(n))))
        self.solid = np.vstack(pts) if pts else np.zeros((0, 3))  # (x, y, r) for clearance checks

    def _background(self):
        """Trees 4.5 m either side of the walk and building walls (with doorways) 11 m out, so scans have
        about as many returns as the real ones at BHEE (~1800 per sweep)."""
        trees, walls = [], []
        for side in (-1, 1):
            p, s = ln.resample(offset_polyline(self.center, side * 4.5), 6.0)
            for x, y in p:
                if dist_to_poly(x, y, self.center) > 3.5:
                    trees.append((x, y, 0.2))
            w, _ = ln.resample(offset_polyline(self.center, side * 11.0), 1.0)
            for i in range(len(w) - 1):
                if i % 5 != 4 and dist_to_poly(*w[i], self.center) > 9 and dist_to_poly(*w[i + 1], self.center) > 9:
                    walls.append((*w[i], *w[i + 1]))
        self.circles = np.vstack((self.circles, np.array(trees).reshape(-1, 3)))
        self.segs = np.vstack((self.segs, np.array(walls).reshape(-1, 4)))

    def dyn(self, t):
        out = [c for f in self.peds for c in f(t)]
        return np.array(out, float).reshape(-1, 3)


def dist_to_poly(x, y, p):
    a, b = p[:-1], p[1:]
    d = b - a
    t = np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / (d * d).sum(1), 0, 1)
    return float(np.hypot(a[:, 0] + t * d[:, 0] - x, a[:, 1] + t * d[:, 1] - y).min())


def offset_polyline(p, d):
    """Polyline shifted d m to its left (mitred corners)."""
    p = np.asarray(p, float)
    if d == 0:
        return p.copy()
    seg = np.diff(p, axis=0)
    nrm = np.column_stack((-seg[:, 1], seg[:, 0])) / np.hypot(*seg.T)[:, None]
    out = [p[0] + d * nrm[0]]
    for i in range(1, len(p) - 1):
        m = nrm[i - 1] + nrm[i]
        m /= np.hypot(*m)
        out.append(p[i] + d * m / max(0.3, float(m @ nrm[i])))
    out.append(p[-1] + d * nrm[-1])
    return np.array(out)


def ped(start, vel, t0=0.0, t1=1e9, lateral=0.2, leg_r=0.06, stand=None):
    """Walking person seen at shin height: two legs that scissor along the walking direction.
    stand=(t_a, t_b): stays at `start` until t_b (if t_a <= t), then walks off with vel."""
    start, vel = np.array(start, float), np.array(vel, float)
    sp = np.hypot(*vel) or 1.0
    u = vel / sp
    n = np.array([-u[1], u[0]])

    def f(t):
        if t < t0 or t > t1:
            return []
        if stand is not None:
            tw = max(0.0, t - stand[1])
            c = start + vel * tw
            ph = 0.0 if tw == 0 else math.sin(2 * math.pi * 0.9 * tw)
        else:
            c = start + vel * (t - t0)
            ph = math.sin(2 * math.pi * 0.9 * (t - t0))
        a = c + n * lateral / 2 + u * 0.15 * ph
        b = c - n * lateral / 2 - u * 0.15 * ph
        return [(a[0], a[1], leg_r), (b[0], b[1], leg_r)]
    return f


def rect_segs(x0, y0, x1, y1):
    return [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]


def bike(x, y_base, y_tip, n=6):
    """A bike parked across the scan plane: sparse rim / tyre / tube returns."""
    ys = np.linspace(y_base, y_tip, n)
    return [(x + 0.03 * (-1) ** i, yy, 0.02) for i, yy in enumerate(ys)]


def scenario(name, v_nom=0.6):
    straight = [(-2.0, 0.0), (34.0, 0.0)]
    rack = []
    for k in range(5):                                        # 5 U-racks across the left half of the walk
        xx = 18.0 + 0.9 * k
        rack += [(xx, 0.45, 0.025), (xx, 1.25, 0.025)]
    bikes = bike(18.9, 1.65, -0.10) + bike(20.7, 1.65, 0.15)  # two bikes stick out into the walk
    can = [(11.0, 0.15, 0.30)]
    if name == "clear":
        return World(straight, name=name)
    if name == "trash_can":
        return World(straight, circles=can, name=name)
    if name == "bike_rack":
        return World(straight, circles=rack + bikes, name=name)
    if name == "narrow_gap":                                  # 1.0 m between a planter and a bench
        segs = rect_segs(14.0, -1.6, 16.0, -0.45) + rect_segs(14.2, 0.55, 16.0, 1.05)
        return World(straight, segs=segs, circles=[(15.0, 0.6, 0.05)], name=name)
    if name == "gap_075":                                     # 0.75 m: fits by the planner's 0.30 m radius
        segs = rect_segs(14.0, -1.6, 16.0, -0.30) + rect_segs(14.2, 0.45, 16.0, 1.6)
        return World(straight, segs=segs, name=name)
    if name == "blocked_then_clear":                          # a group across the whole walk, leaves after ~6 s
        t_leave = 10.0 / (0.94 * v_nom) + 7.0
        ps = [ped((12.0, yy), (0.0, 1.0 if yy > 0 else -1.0), stand=(0, t_leave))
              for yy in np.arange(-1.65, 1.66, 0.55)]
        return World(straight, peds=ps, name=name)
    if name == "barrier":                                     # permanent barrier; the only way is over grass
        return World(straight, segs=[(12.0, -2.6, 12.0, 1.6)], name=name)
    if name == "oncoming_ped":                                # walks through the gap the robot wants
        return World(straight, peds=[ped((30.0, -0.6), (-1.3, 0.0))], circles=can, name=name)
    if name == "crossing_ped":
        t_cross = (13.0 - 1.2) / (0.94 * v_nom)                 # crosses the route ~1-2 m in front of the robot
        return World(straight, peds=[ped((13.0, -4.0), (0.0, 1.2), t0=t_cross - 4.0 / 1.2)], name=name)
    if name == "osm_offset":                                  # route 0.9 m left of the true centre line
        return World(straight, circles=can + rack + bikes, route_offset=0.9, name=name)
    if name == "gps_jump":                                    # fused pose jumps 0.8 m mid-avoidance (see run)
        return World(straight, circles=can, name=name)
    if name == "corner_obstacle":
        c = [(-2.0, 0.0), (16.0, 0.0), (16.0, 18.0)]
        obs = [(16.35, 3.2, 0.30), (15.2, 7.0, 0.05), (16.5, 7.4, 0.05)]
        segs = rect_segs(17.0, -1.0, 18.0, 1.0)              # utility box on the corner's outside
        return World(c, circles=obs, segs=segs, name=name)
    if name == "campus_mix":
        c = [(-2.0, 0.0), (22.0, 0.0), (22.0, 20.0), (42.0, 20.0)]
        obs = [(8.0, -0.2, 0.30)] + [(22.4, 6.0 + 0.9 * k, 0.025) for k in range(4)] \
            + [(21.4, 6.0 + 0.9 * k, 0.025) for k in range(4)] + bike(22.0, 8.2, 8.25)[:1] \
            + [(30.0, 20.3, 0.30), (34.0, 19.6, 0.35)]
        segs = rect_segs(14.0, -1.6, 15.5, -0.45) + rect_segs(14.0, 0.55, 15.5, 1.6)
        bk = [(22.0 + 0.6 - 0.25 * i, 8.6, 0.02) for i in range(6)]      # a bike lying across the walk
        return World(c, circles=obs + bk, segs=segs, peds=[ped((40.0, 20.2), (-1.2, 0.0), t0=30.0)], name=name)
    raise SystemExit(f"unknown scenario {name}")


SCENARIOS = ["clear", "trash_can", "bike_rack", "narrow_gap", "gap_075", "blocked_then_clear", "barrier",
             "oncoming_ped", "crossing_ped", "osm_offset", "gps_jump", "corner_obstacle", "campus_mix"]


# ================================================================ LiDAR
class Lidar:
    N = 2160
    SWEEP = 0.1

    def __init__(self, rng, front_deg=ln.FRONT_DEG):
        self.rng, self.front = rng, front_deg
        self.buf = []
        self.k = 0
        self.phase = rng.random()

    def slice(self, world, t, pose, k):
        """Cast beams k*N/10 .. (k+1)*N/10 (10 ms of the sweep) from the true pose."""
        n = self.N // 10
        j = np.arange(k * n, (k + 1) * n) + self.phase
        a = j * 360.0 / self.N                                   # LiDAR angle, clockwise
        x, y, h = pose
        th = h + np.radians(self.front - a)
        dx, dy = np.cos(th), np.sin(th)
        best = np.full(n, np.inf)
        C = np.vstack((world.circles, world.dyn(t)))
        if len(C):
            near = np.hypot(C[:, 0] - x, C[:, 1] - y) < 26
            C = C[near]
            ocx, ocy = C[:, 0] - x, C[:, 1] - y
            b = dx[:, None] * ocx[None] + dy[:, None] * ocy[None]
            c2 = ocx ** 2 + ocy ** 2 - C[:, 2] ** 2
            disc = b * b - c2[None]
            sq = np.sqrt(np.maximum(disc, 0))
            tt = np.where(b - sq > 0, b - sq, b + sq)
            tt = np.where((disc >= 0) & (tt > 0), tt, np.inf)
            best = np.minimum(best, tt.min(1))
        S = world.segs
        if len(S):
            px, py = S[:, 0] - x, S[:, 1] - y
            ex, ey = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
            den = dx[:, None] * ey[None] - dy[:, None] * ex[None]
            with np.errstate(divide="ignore", invalid="ignore"):
                tt = (px[None] * ey[None] - py[None] * ex[None]) / den
                u = (px[None] * dy[:, None] - py[None] * dx[:, None]) / den
            ok = (np.abs(den) > 1e-12) & (tt > 0) & (u >= 0) & (u <= 1)
            best = np.minimum(best, np.where(ok, tt, np.inf).min(1))
        d = best + self.rng.normal(0, 0.012, n)
        keep = np.isfinite(best) & (best < 25.0) & (self.rng.random(n) > 0.02)
        mast = (a > 200) & (a < 237)
        d = np.where(mast, 0.030, d)
        keep |= mast
        for ai, di in zip(a[keep], d[keep]):
            self.buf.append((float(ai % 360.0), float(round(di * 1000.0)), 100.0))
        if k == 9:
            if self.rng.random() < SELF_RETURN_P:                # intermittent self-return, +52 deg, 0.18 m
                a52 = self.front - 52.0
                self.buf += [(a52 + 0.17 * i, 180.0, 60.0) for i in range(5)]
            scan = sorted(self.buf)
            self.buf = []
            self.phase = self.rng.random()
            return scan
        return None


# ================================================================ robot
class Robot:
    def __init__(self, model, pose, rng):
        self.model = model
        self.x, self.y, self.h = pose
        self.rng = rng
        self.vl = self.vr = 0.0                                   # wheel surface speed (m/s, as odometry sees)
        self.cmd = (0.0, 0.0)
        nw = int(round(0.30 / DT))
        self.wbuf = [(0.0, 0.0)] * nw                             # wheel-loop dead time
        ny = int(round((0.35 if model == "taped" else 0.0) / DT))
        self.ybuf = [0.0] * ny                                    # extra yaw dead time (taped wheels)
        self.r = 0.0
        self.stuck, self.wound, self.release, self.still_t = False, 0.0, 0.0, 0.0
        self.slip = 0.98                                          # ground speed / what the wheels report
        self.gyro_bias = math.radians(0.15) * (1 if rng.random() < 0.5 else -1)

    def step(self):
        self.wbuf.append(self.cmd)
        cl, cr = self.wbuf.pop(0)
        cap = 175 / 60 * WHEEL_C * WHEEL_SCALE
        cl, cr = max(-cap, min(cap, cl)), max(-cap, min(cap, cr))
        a = DT / 0.25
        self.vl += a * (cl - self.vl)
        self.vr += a * (cr - self.vr)
        v = (self.vl + self.vr) / 2 * self.slip
        r_kin = 1.04 * (self.vr - self.vl) / TRACK_EFF            # fitted turn gain 1.04 on the commanded rate
        if self.ybuf:
            self.ybuf.append(r_kin)
            r_kin = self.ybuf.pop(0)
        if self.model == "taped":                                 # stick-slip of the scrubbing passive wheels
            brk = math.radians(np.interp(abs(v), [0.1, 0.15, 0.3, 0.6], [6.0, 4.0, 1.5, 0.5]))
            if self.stuck:
                self.wound += r_kin * DT
                target = 0.0
                if abs(self.wound) > brk:
                    self.stuck, self.release = False, self.wound
            else:
                target = r_kin + self.release / 0.2
                self.release -= self.release / 0.2 * DT
                if abs(r_kin) < math.radians(1.5) and abs(self.r) < math.radians(1.5):
                    self.still_t += DT
                    if self.still_t > 0.3:
                        self.stuck, self.wound, self.still_t = True, 0.0, 0.0
                else:
                    self.still_t = 0.0
        else:
            target = r_kin
        self.r += DT / 0.1 * (target - self.r)
        self.h = ln.wrap(self.h + self.r * DT)
        self.x += v * DT * math.cos(self.h)
        self.y += v * DT * math.sin(self.h)

    def gz(self):
        return self.r + self.gyro_bias + self.rng.normal(0, math.radians(0.3))


def rect_clearance(pose, solid):
    """Smallest gap (m) between the chassis rectangle and any obstacle (negative = overlap)."""
    if len(solid) == 0:
        return 99.0
    x, y, h = pose
    c, s = math.cos(h), math.sin(h)
    dx, dy = solid[:, 0] - x, solid[:, 1] - y
    px, py = c * dx + s * dy, -s * dx + c * dy
    ex = np.maximum(np.maximum(FP[0] - px, px - FP[1]), 0)
    ey = np.maximum(np.maximum(FP[2] - py, py - FP[3]), 0)
    inside = (ex == 0) & (ey == 0)
    d = np.hypot(ex, ey) - solid[:, 2]
    d = np.where(inside, -solid[:, 2] - np.minimum(np.minimum(px - FP[0], FP[1] - px),
                                                    np.minimum(py - FP[2], FP[3] - py)), d)
    return float(d.min())


def off_walk(pose, world):
    """How far (m) the chassis's corners stick out past the sidewalk edge."""
    x, y, h = pose
    c, s = math.cos(h), math.sin(h)
    worst = 0.0
    p, sp = world.center, None
    for cx_, cy_ in ((FP[0], FP[2]), (FP[0], FP[3]), (FP[1], FP[2]), (FP[1], FP[3])):
        qx, qy = x + c * cx_ - s * cy_, y + s * cx_ + c * cy_
        if sp is None:
            seg = np.diff(p, axis=0)
            sp = (seg * seg).sum(1)
        a = p[:-1]
        t = np.clip(((qx - a[:, 0]) * seg[:, 0] + (qy - a[:, 1]) * seg[:, 1]) / sp, 0, 1)
        d = np.hypot(a[:, 0] + t * seg[:, 0] - qx, a[:, 1] + t * seg[:, 1] - qy).min()
        worst = max(worst, d - world.half_w)
    return worst


# ================================================================ one run
def run(scn, model="taped", speed=0.6, baseline=False, seed=1, map_frame="odom", lookahead=1.5,
        min_radius=1.0, record=False, nav_kw=None, recover=True, adaptive_la=True):
    rng = np.random.default_rng(seed)
    world = scenario(scn, speed)
    route_pts = world.route
    h0 = math.atan2(route_pts[1][1] - route_pts[0][1], route_pts[1][0] - route_pts[0][0])
    start = world.center[0] + 0.0
    robot = Robot(model, (start[0] + 2.0 * math.cos(h0), start[1] + 2.0 * math.sin(h0), h0), rng)
    lidar = Lidar(rng)
    nav = ln.LocalNav(**(nav_kw or {}))
    nav.set_route(route_pts)
    rp, rs = ln.resample(route_pts, 0.1)
    L = rs[-1]
    odom = [robot.x, robot.y, robot.h]
    fused_err = np.zeros(3)
    t, nxt_ctrl = 0.0, 0.0
    S = {"s": ln.project(rp, rs, robot.x, robot.y)[0], "i": 0.0}
    scan = None
    pending = None
    out = {"t": [], "x": [], "y": [], "h": [], "v": [], "why": [], "clear": [], "off": []}
    plans, frames = [], []
    T_max = (L / (0.94 * speed)) * (1.6 if baseline else 2.5) + (20 if baseline else 40)
    reason = "time limit"
    k_slice = 0
    jump_done = False
    stats = {"guard_stop_s": 0.0, "guard_slow_s": 0.0, "blocked_s": 0.0, "plans": 0, "plan_fail": 0, "widened": 0,
             "contact_s": 0.0, "first_contact": None, "min_clear": 99.0, "max_off": 0.0}
    gz_meas = 0.0
    while t < T_max:
        # ---- physics + LiDAR slice
        robot.step()
        true_pose = (robot.x, robot.y, robot.h)
        sc = lidar.slice(world, t, true_pose, k_slice)
        k_slice = (k_slice + 1) % 10
        if sc is not None:
            scan = sc
        # odometry: wheels + gyro (what follow.py integrates)
        gz_meas = robot.gz()
        odom[2] = ln.wrap(odom[2] + gz_meas * DT)
        vo = (robot.vl + robot.vr) / 2
        odom[0] += vo * DT * math.cos(odom[2])
        odom[1] += vo * DT * math.sin(odom[2])
        # fused: truth + RTK wander (+ the gps_jump step)
        fused_err[:2] += -fused_err[:2] * DT / 5.0 + rng.normal(0, 0.03 * math.sqrt(2 * DT / 5.0), 2)
        fused_err[2] += -fused_err[2] * DT / 10.0 + rng.normal(0, math.radians(0.5) * math.sqrt(2 * DT / 10.0))
        if scn == "gps_jump" and not jump_done and robot.x > 11.0 - 3.0:
            fused_err[1] += 0.8
            jump_done = True
        fused = (robot.x + fused_err[0], robot.y + fused_err[1], ln.wrap(robot.h + fused_err[2]))
        odom_pose = tuple(odom) if map_frame == "odom" else fused
        if sc is not None and not baseline:
            nav.add_scan(sc, odom_pose)
        t += DT
        # ---- 20 Hz control (follow.py's follow phase)
        if t + 1e-9 < nxt_ctrl:
            continue
        nxt_ctrl += 0.05
        if pending is not None:                                  # plans land one tick late (planner thread)
            nav.cur = pending
            pending = None
        S["s"], xt = ln.project(rp, rs, fused[0], fused[1])
        if S["s"] >= L - 0.3:
            reason = "arrived"
            break
        v = speed * min(1.0, (L - S["s"]) / 1.0 + 0.3)
        why = ""
        if baseline:
            tx, ty = ln.at_extended(rp, rs, S["s"] + lookahead)
            px, py, ph = fused
            fac, why = baseline_guard(scan)
        else:
            if nav.due(t):
                old = nav.cur
                r = nav.plan(odom_pose, fused, S["s"], now=t)
                stats["plans"] += 1
                stats["plan_fail"] += 0 if r["ok"] else 1
                stats["widened"] += 1 if r.get("why") == "corridor widened" else 0
                if record:
                    plans.append(dict(t=round(t, 2), ok=r["ok"], why=r["why"], ms=r["ms"],
                                      dev=r.get("deviation"), side=path_side(r, rp, rs, odom_pose, fused, S["s"]),
                                      path=r["path"][::3].round(3).tolist() if r["ok"] else None,
                                      odom=list(odom_pose), fused=list(fused)))
                else:
                    plans.append(dict(t=round(t, 2), ok=r["ok"], ms=r["ms"],
                                      side=path_side(r, rp, rs, odom_pose, fused, S["s"])))
                pending = nav.cur
                nav.cur = old
            res_ = nav.result
            if not res_.get("ok"):
                tx = None
                why = "path blocked: " + res_.get("why", "")
            else:
                tx, ty = nav.target(odom_pose, nav.lookahead(lookahead) if adaptive_la else lookahead)
                v = nav.speed_limit(v)
            px, py, ph = odom_pose
            fac, gwhy = nav.guard(scan, odom_pose, v) if scan is not None else (0.0, "no scan")
            why = why or gwhy
        if tx is None:
            v = w = 0.0
            stats["blocked_s"] += 0.05
        else:
            alpha = ln.wrap(math.atan2(ty - py, tx - px) - ph)
            Ld = math.hypot(tx - px, ty - py) or lookahead
            k = max(-1 / min_radius, min(1 / min_radius, 2 * math.sin(alpha) / Ld))
            w = v * k
            if fac == 0.0:
                stats["guard_stop_s"] += 0.05
            elif fac < 1.0:
                stats["guard_slow_s"] += 0.05
            v, w = v * fac, w * fac
            if 0 < v < 0.15:
                w *= 0.15 / v
                v = 0.15
        # ---- recovery: held by the guard with a plan -> back straight up a little
        back = 0.0
        if not baseline and recover and scan is not None:
            S["held"] = S.get("held", 0.0) + 0.05 if (tx is not None and fac == 0.0) else 0.0
            back = nav.recovery(scan, odom_pose, S["held"])
            if back < 0:
                stats["backups_s"] = stats.get("backups_s", 0.0) + 0.05
                S["held"] = 0.0
                why = "backing up"
        gz = gz_meas - 0.0                                        # follow.py subtracts its bias estimate
        if back < 0:
            robot.cmd = (back * WHEEL_SCALE, back * WHEEL_SCALE)
            S["i"] = 0.0
            v = back
        elif v <= 0:
            robot.cmd = (0.0, 0.0)
            S["i"] = 0.0
        else:
            err = w - gz
            S["i"] = max(-0.2, min(0.2, S["i"] + err / 20))
            w_cmd = w + 0.4 * err + 1.0 * S["i"]
            w_cmd = max(-v / min_radius, min(v / min_radius, w_cmd))
            vl, vr = v - w_cmd * TRACK_EFF / 2, v + w_cmd * TRACK_EFF / 2
            lo = 0.3 * max(vl, vr)
            vl, vr = max(vl, lo), max(vr, lo)
            robot.cmd = (vl * WHEEL_SCALE, vr * WHEEL_SCALE)      # rpm_for() ignores WHEEL_SCALE: ground is 6 % slower
        dyn = world.dyn(t)
        cl_static = rect_clearance(true_pose, world.solid)
        cl = min(cl_static, rect_clearance(true_pose, dyn)) if len(dyn) else cl_static
        off = off_walk(true_pose, world)
        stats["min_clear"] = min(stats["min_clear"], cl)
        stats["min_clear_static"] = min(stats.get("min_clear_static", 99.0), cl_static)
        stats["max_off"] = max(stats["max_off"], off)
        if cl < 0:
            stats["contact_s"] += 0.05
            moving = abs(robot.vl + robot.vr) / 2 > 0.05
            stats["contact_moving_s"] = stats.get("contact_moving_s", 0.0) + (0.05 if moving else 0.0)
            if stats["first_contact"] is None:
                stats["first_contact"] = round(t, 2)
                stats["contact_speed"] = round(abs(robot.vl + robot.vr) / 2 * robot.slip, 3)
        if record and len(dyn) and len(out["t"]) % 20 == 0:
            out.setdefault("peds", []).append([round(t, 2), dyn[:, :2].round(2).tolist()])
        out["t"].append(round(t, 2)); out["x"].append(round(robot.x, 3)); out["y"].append(round(robot.y, 3))
        out["h"].append(round(robot.h, 4)); out["v"].append(round(v, 3)); out["why"].append(why)
        out["clear"].append(round(cl, 3)); out["off"].append(round(off, 3))
        if record and not baseline and len(out["t"]) % 10 == 0 and nav.map.x0 is not None:
            frames.append(t)
    flips = side_flips([p["side"] for p in plans])
    ms = np.array([p["ms"] for p in plans]) if plans else np.zeros(1)
    sm = np.array(nav.stats["scan_ms"]) if nav.stats["scan_ms"] else np.zeros(1)
    vv = np.array(out["v"])
    summary = dict(scenario=scn, model=model, speed=speed, baseline=baseline, map_frame=map_frame, seed=seed,
                   reason=reason, t_end=round(t, 1), route_m=round(float(L), 1),
                   progress=round(float(S["s"]) / float(L), 3),
                   collided=stats["contact_s"] > 0, contact_s=round(stats["contact_s"], 2),
                   contact_moving_s=round(stats.get("contact_moving_s", 0.0), 2),
                   contact_speed=stats.get("contact_speed"),
                   first_contact=stats["first_contact"], min_clear=round(stats["min_clear"], 3),
                   min_clear_static=round(stats.get("min_clear_static", 99.0), 3),
                   max_off_walk=round(stats["max_off"], 3), guard_stop_s=round(stats["guard_stop_s"], 1),
                   guard_slow_s=round(stats["guard_slow_s"], 1), blocked_s=round(stats["blocked_s"], 1),
                   backup_s=round(stats.get("backups_s", 0.0), 1),
                   plans=stats["plans"], plan_fail=stats["plan_fail"], widened=stats["widened"], side_flips=flips,
                   avg_speed=round(float(L) * min(1.0, float(S["s"]) / float(L)) / max(t, 1e-9), 3),
                   plan_ms_med=round(float(np.median(ms)), 2), plan_ms_p95=round(float(np.percentile(ms, 95)), 2),
                   plan_ms_max=round(float(ms.max()), 2), scan_ms_med=round(float(np.median(sm)), 2),
                   scan_ms_p95=round(float(np.percentile(sm, 95)), 2))
    if record:
        M = nav.map
        summary["trace"] = out
        summary["plans_rec"] = plans
        summary["final_map"] = dict(x0=M.x0, y0=M.y0, res=M.res, occ=np.argwhere(M.occupied()).tolist())
    return summary, world


def path_side(r, rp, rs, odom_pose, fused, s_now):
    """Which side of the route the plan passes on, 2-5 m ahead: +1 left, -1 right, 0 on it."""
    if not r.get("ok"):
        return None
    p = r["path"]
    ps = r["path_s"]
    m = (ps > 2.0) & (ps < 5.0)
    if not m.any():
        return 0
    # path (odom) -> fused, then signed offset from the route
    ox, oy, oh = odom_pose
    fx, fy, fh = fused
    d = ln.wrap(fh - oh)
    c, s = math.cos(d), math.sin(d)
    q = p[m]
    qx, qy = fx + c * (q[:, 0] - ox) - s * (q[:, 1] - oy), fy + s * (q[:, 0] - ox) + c * (q[:, 1] - oy)
    best = 0.0
    for x_, y_ in zip(qx, qy):
        sq, dist = ln.project(rp, rs, x_, y_)
        i = min(int(np.searchsorted(rs, sq)), len(rs) - 1)
        i0 = max(0, i - 1)
        tx, ty = rp[min(i0 + 1, len(rp) - 1)] - rp[i0]
        side = math.copysign(dist, tx * (y_ - rp[i0][1]) - ty * (x_ - rp[i0][0]))
        if abs(side) > abs(best):
            best = side
    return 0 if abs(best) < 0.25 else (1 if best > 0 else -1)


def side_flips(sides):
    seq = [s for s in sides if s]
    return int(sum(1 for a, b in zip(seq, seq[1:]) if a != b))


def baseline_guard(scan):
    """follow.py's lidar_check today (straight corridor 0.45 m, stop 0.8, slow 2.0, anything within 0.25 m)."""
    if scan is None:
        return 0.0, "no scan"
    sys.path.insert(0, os.path.join(HERE, "..", "motor_cal"))
    from lidar_odom import scan_to_points
    pts = scan_to_points(scan)
    if len(pts) == 0:
        return 1.0, ""
    x, y = pts[:, 0], pts[:, 1]
    r = np.hypot(x, y)
    if (r < 0.25).any():
        return 0.0, "something within 0.25 m"
    ahead = (x > 0) & (np.abs(y) < 0.45)
    if ahead.any():
        d = x[ahead].min()
        if d < 0.8:
            return 0.0, f"obstacle {d:.2f} m ahead"
        if d < 2.0:
            return 0.5, "slowing"
    return 1.0, ""


# ================================================================ plotting
def plot(summary, world, path_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tr = summary["trace"]
    fig, ax = plt.subplots(figsize=(14, 5.2))
    c = world.center
    for side in (-1, 1):
        e = offset_polyline(c, side * world.half_w)
        ax.plot(e[:, 0], e[:, 1], color="#7a9a5a", lw=1)
    ax.plot(world.route[:, 0], world.route[:, 1], "b--", lw=1, label="route")
    nc, ns = world.n_fg
    for x_, y_, r_ in world.circles[:nc]:
        ax.add_patch(plt.Circle((x_, y_), r_, color="k"))
    for x1, y1, x2, y2 in world.segs[:ns]:
        ax.plot([x1, x2], [y1, y2], "k-", lw=2)
    lo, hi = c.min(0) - world.half_w - 1.0, c.max(0) + world.half_w + 1.0
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    for k, (tp, legs) in enumerate(tr.get("peds", [])):
        lg = np.array(legs)
        ax.plot(lg[:, 0], lg[:, 1], ".", color="#8a8a8a", ms=3, label="people (every 1 s)" if k == 0 else None)
    ax.plot(tr["x"], tr["y"], "-", color="#d0442c", lw=1.6, label="robot (truth)")
    for i in range(0, len(tr["t"]), 20):
        x, y, h = tr["x"][i], tr["y"][i], tr["h"][i]
        cs, sn = math.cos(h), math.sin(h)
        cor = [(FP[0], FP[2]), (FP[1], FP[2]), (FP[1], FP[3]), (FP[0], FP[3]), (FP[0], FP[2])]
        ax.plot([x + cs * a - sn * b for a, b in cor], [y + sn * a + cs * b for a, b in cor], color="#d0442c", lw=0.4,
                alpha=0.5)
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8)
    s = summary
    ax.set_title(f"{s['scenario']} | {s['model']} {s['speed']} m/s{' BASELINE' if s['baseline'] else ''} | {s['reason']} "
                 f"t={s['t_end']} s | min clear {s['min_clear']:.2f} m | off walk {s['max_off_walk']:.2f} m | "
                 f"flips {s['side_flips']}")
    plt.tight_layout()
    plt.savefig(path_png, dpi=90)
    plt.close(fig)


# ================================================================ CLI
def _job(args):
    scn, model, speed, baseline, seed, kw = args
    s, _ = run(scn, model, speed, baseline=baseline, seed=seed, **kw)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?", help="one scenario (default: the whole matrix)")
    ap.add_argument("--model", default="taped", choices=("taped", "casters"))
    ap.add_argument("--speed", type=float, default=0.6)
    ap.add_argument("--baseline", action="store_true", help="today's follow.py instead of the local planner")
    ap.add_argument("--map-frame", default="odom", choices=("odom", "fused"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--plot", help="PNG path for a single run")
    ap.add_argument("--out", default="sim_results.json")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--seeds", type=int, default=1, help="matrix: seeds per cell")
    a = ap.parse_args()
    if a.scenario:
        t0 = time.time()
        s, w = run(a.scenario, a.model, a.speed, a.baseline, a.seed, map_frame=a.map_frame, record=bool(a.plot))
        if a.plot:
            plot(s, w, a.plot)
        for k in ("trace", "plans_rec", "final_map"):
            s.pop(k, None)
        print(json.dumps(s, indent=1))
        print(f"wall time {time.time() - t0:.1f} s")
        return
    jobs = []
    for seed in range(1, a.seeds + 1):
        for scn in SCENARIOS:
            for model, speeds in (("taped", (0.3, 0.6)), ("casters", (0.3, 0.6, 0.8))):
                for sp in speeds:
                    jobs.append((scn, model, sp, False, seed, {}))
            jobs.append((scn, "taped", 0.3, True, seed, {}))           # today's follow.py, today's robot
        for model in ("taped", "casters"):                                # costmap in the GPS-fused frame instead
            jobs.append(("gps_jump", model, 0.6, False, seed, {"map_frame": "fused"}))
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(a.jobs) as pool:
        res = []
        for i, s in enumerate(pool.imap_unordered(_job, jobs)):
            res.append(s)
            json.dump(res, open(a.out, "w"), indent=1)                     # partial results as they come in
            print(f"[{i + 1}/{len(jobs)}] {s['scenario']:20s} {s['model']:7s} {s['speed']:.1f} "
                  f"{'BASE ' if s['baseline'] else ''}{s['reason']:10s} clear {s['min_clear']:+.2f} "
                  f"off {s['max_off_walk']:.2f} flips {s['side_flips']} t {s['t_end']:.0f}s", flush=True)
    json.dump(res, open(a.out, "w"), indent=1)
    print(f"{len(res)} runs in {time.time() - t0:.0f} s -> {a.out}")


if __name__ == "__main__":
    main()
