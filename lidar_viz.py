#!/usr/bin/env python3
"""
Live STL-27L point cloud + occupancy grid (matplotlib animation).

Assumes the LiDAR is stationary at the grid origin (no odometry / SLAM), so the
grid accumulates evidence from the same pose over time.

Usage:    .venv/bin/python lidar_viz.py [--port /dev/ttyAMA0] [--res 0.05] [--size 16]
          .venv/bin/python lidar_viz.py --plan      # local costmap + A*, click to set goal
Keys:     s = save map (map.pgm + map.yaml + map.npy)   r = reset grid   q = quit
"""
import argparse
import os
import threading
import time

# Over SSH there is no DISPLAY and matplotlib silently falls back to the non-GUI Agg
# backend; target the Pi's attached screen instead.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ["DISPLAY"] = ":0"

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
from matplotlib.animation import FuncAnimation

from lidar import STL27L

# log-odds occupancy parameters
L_OCC, L_FREE, L_MIN, L_MAX = 0.85, -0.4, -4.0, 4.0


class ScanReader(threading.Thread):
    """Reads scans in the background and keeps only the newest one."""

    def __init__(self, lidar):
        super().__init__(daemon=True)
        self.lidar = lidar
        self.lock = threading.Lock()
        self.scan = None
        self.seq = 0
        self.hz = 0.0

    def run(self):
        t0, n = time.time(), 0
        for scan in self.lidar.scans():
            with self.lock:
                self.scan, self.seq = scan, self.seq + 1
            n += 1
            if time.time() - t0 >= 1.0:
                self.hz, t0, n = n / (time.time() - t0), time.time(), 0

    def latest(self):
        with self.lock:
            return self.scan, self.seq


class OccupancyGrid:
    """Log-odds grid centred on the sensor; each scan's rays mark free space up to the hit."""

    def __init__(self, size_m, res, max_range):
        self.res, self.max_range = res, max_range
        self.n = int(round(size_m / res))
        self.origin = -size_m / 2                  # world coord of the grid's lower-left corner
        self.logodds = np.zeros((self.n, self.n), np.float32)

    def reset(self):
        self.logodds[:] = 0

    def _cells(self, x, y):
        ix = ((x - self.origin) / self.res).astype(np.int64)
        iy = ((y - self.origin) / self.res).astype(np.int64)
        ok = (ix >= 0) & (ix < self.n) & (iy >= 0) & (iy < self.n)
        return iy[ok] * self.n + ix[ok]            # flat index, row = y

    def update(self, ang, dist):
        keep = dist <= self.max_range
        ang, dist = ang[keep], dist[keep]
        if dist.size == 0:
            return
        # sample each ray every half cell, stopping one cell short of the hit
        steps = np.arange(0, self.max_range, self.res / 2, dtype=np.float32)
        r = steps[None, :] * np.ones((dist.size, 1), np.float32)
        mask = r < (dist[:, None] - self.res)
        rr = r[mask]
        aa = np.broadcast_to(ang[:, None], r.shape)[mask]
        free = np.unique(self._cells(rr * np.sin(aa), rr * np.cos(aa)))
        occ = np.unique(self._cells(dist * np.sin(ang), dist * np.cos(ang)))
        free = np.setdiff1d(free, occ, assume_unique=True)

        flat = self.logodds.ravel()
        flat[free] += L_FREE
        flat[occ] += L_OCC
        np.clip(flat, L_MIN, L_MAX, out=flat)

    def probability(self):
        return 1.0 / (1.0 + np.exp(-self.logodds))

    def save(self, stem="map"):
        p = self.probability()
        img = np.full(p.shape, 205, np.uint8)      # ROS map_server convention: 205 = unknown
        img[p > 0.65] = 0
        img[p < 0.35] = 254
        img = np.flipud(img)                       # PGM rows go top-down
        with open(f"{stem}.pgm", "wb") as f:
            f.write(f"P5\n{self.n} {self.n}\n255\n".encode())
            f.write(img.tobytes())
        with open(f"{stem}.yaml", "w") as f:
            f.write(f"image: {stem}.pgm\nresolution: {self.res}\n"
                    f"origin: [{self.origin}, {self.origin}, 0.0]\nnegate: 0\n"
                    f"occupied_thresh: 0.65\nfree_thresh: 0.35\n")
        np.save(f"{stem}.npy", p)
        print(f"saved {stem}.pgm / {stem}.yaml / {stem}.npy")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--res", type=float, default=0.05, help="grid cell size (m)")
    ap.add_argument("--size", type=float, default=16.0, help="grid side length (m)")
    ap.add_argument("--max-range", type=float, default=8.0, help="ignore returns beyond this (m)")
    ap.add_argument("--view", type=float, default=6.0, help="point cloud plot radius (m)")
    plan = ap.add_argument_group("local planning (--plan)")
    plan.add_argument("--plan", action="store_true",
                      help="show a robot-centric local costmap + A* path instead of the occupancy grid")
    plan.add_argument("--local-size", type=float, default=8.0, help="local costmap side length (m)")
    plan.add_argument("--robot-radius", type=float, default=0.25, help="hard clearance (m)")
    plan.add_argument("--inflation", type=float, default=0.6, help="soft-cost band beyond robot radius (m)")
    plan.add_argument("--memory", type=float, default=0.5, help="seconds of scans kept as obstacles")
    plan.add_argument("--min-range", type=float, default=None,
                      help="ignore returns closer than this, i.e. the robot's own body (m, default: robot radius)")
    args = ap.parse_args()

    reader = ScanReader(STL27L(args.port))
    reader.start()

    fig, (ax_pc, ax_grid) = plt.subplots(1, 2, figsize=(13, 6.5))
    fig.canvas.manager.set_window_title("STL-27L")

    # 0 deg = forward = +y (up); angles increase clockwise as seen from above
    sc = ax_pc.scatter([], [], c=[], s=2, vmin=0, vmax=255)
    ax_pc.plot(0, 0, marker="^", markersize=10, color="C3")
    ax_pc.set(xlim=(-args.view, args.view), ylim=(-args.view, args.view),
              aspect="equal", xlabel="x (m)", ylabel="y (m, forward)", title="Point cloud")
    ax_pc.grid(True, alpha=0.3)
    fig.colorbar(sc, ax=ax_pc, label="intensity", shrink=0.8)

    if args.plan:
        from local_planner import LocalCostmap, OCCUPIED, UNKNOWN
        cmap = LocalCostmap(args.local_size, args.res, args.robot_radius, args.inflation, args.memory,
                            min_range=args.min_range)
        h = cmap.half
        im = ax_grid.imshow(np.zeros((cmap.n, cmap.n)), origin="lower", extent=(-h, h, -h, h),
                            cmap="gray_r", vmin=0, vmax=1, interpolation="nearest")
        ax_grid.add_patch(plt.Circle((0, 0), args.robot_radius, fill=False, color="C3"))
        path_line, = ax_grid.plot([], [], color="C0", lw=2)
        path_pc, = ax_pc.plot([], [], color="C0", lw=2)
        goal_mark, = ax_grid.plot([], [], marker="x", markersize=10, mew=2, color="C1", ls="")
        plan_text = ax_grid.text(0.02, 0.98, "click to set a goal", transform=ax_grid.transAxes,
                                 va="top", bbox=dict(facecolor="white", alpha=0.8, edgecolor="none"))
        ax_grid.set(xlabel="x (m)", ylabel="y (m, forward)",
                    title=f"Local costmap ({args.res * 100:.0f} cm cells)")
        goal = [None]
        plan_msg = ["no goal"]

        def render_costmap():
            img = np.zeros(cmap.cost.shape, np.float32)          # free = white
            img[cmap.state == UNKNOWN] = 0.2
            soft = np.isfinite(cmap.cost) & (cmap.cost > 1.0 + cmap.unknown_cost * (cmap.state == UNKNOWN))
            img[soft] = np.maximum(img[soft], 0.25 + 0.3 * (cmap.cost[soft] - 1) / 10)
            img[~np.isfinite(cmap.cost)] = 0.65                  # inflated: robot centre can't go here
            img[cmap.state == OCCUPIED] = 1.0
            return img

        def process(a, d):
            cmap.update(a, d)
            im.set_data(render_costmap())
            if goal[0] is None:
                path = None
            else:
                t0 = time.perf_counter()
                path, msg = cmap.plan(goal[0])
                plan_msg[0] = f"{msg} ({(time.perf_counter() - t0) * 1000:.0f} ms)"
                plan_text.set_text(msg if path else f"NO PATH: {msg}")
                plan_text.set_color("black" if path else "C3")
            xs, ys = zip(*path) if path else ((), ())
            path_line.set_data(xs, ys)
            path_pc.set_data(xs, ys)
            return plan_msg[0]

        def on_click(ev):
            if ev.inaxes not in (ax_grid, ax_pc):
                return
            if ev.button == 1:
                goal[0] = (ev.xdata, ev.ydata)
                goal_mark.set_data([ev.xdata], [ev.ydata])
            elif ev.button == 3:
                goal[0] = None
                goal_mark.set_data([], [])
                plan_msg[0] = "no goal"
                plan_text.set_text("click to set a goal")
                plan_text.set_color("black")

        fig.canvas.mpl_connect("button_press_event", on_click)
        keys = "click=goal right-click=clear q=quit"
    else:
        grid = OccupancyGrid(args.size, args.res, args.max_range)
        ext = (grid.origin, -grid.origin, grid.origin, -grid.origin)
        im = ax_grid.imshow(grid.probability(), origin="lower", extent=ext,
                            cmap="gray_r", vmin=0, vmax=1, interpolation="nearest")
        ax_grid.plot(0, 0, marker="^", markersize=8, color="C3")
        ax_grid.set(xlabel="x (m)", ylabel="y (m, forward)",
                    title=f"Occupancy grid ({args.res * 100:.0f} cm cells)")
        fig.colorbar(im, ax=ax_grid, label="P(occupied)", shrink=0.8)

        def process(a, d):
            grid.update(a, d)
            im.set_data(grid.probability())
            return ""

        def on_key(ev):
            if ev.key == "s":
                grid.save()
            elif ev.key == "r":
                grid.reset()

        fig.canvas.mpl_connect("key_press_event", on_key)
        keys = "s=save r=reset q=quit"

    status = fig.text(0.01, 0.01, "waiting for data...", family="monospace")
    fig.tight_layout(rect=(0, 0.03, 1, 1))

    last_seq = [0]

    def update(_):
        scan, seq = reader.latest()
        if scan is None or seq == last_seq[0]:
            return
        last_seq[0] = seq
        a = np.radians([p[0] for p in scan]).astype(np.float32)
        d = np.array([p[1] for p in scan], np.float32) / 1000.0
        inten = np.array([p[2] for p in scan])

        sc.set_offsets(np.column_stack((d * np.sin(a), d * np.cos(a))))
        sc.set_array(inten)
        extra = process(a, d)
        status.set_text(f"{reader.hz:4.1f} Hz | {len(scan):4d} pts | "
                        f"{reader.lidar.speed_dps / 360:4.1f} rev/s | "
                        f"crc errs {reader.lidar.crc_errors} | {extra + ' | ' if extra else ''}{keys}")

    anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)  # noqa: F841 (keep ref)
    plt.show()


if __name__ == "__main__":
    main()
