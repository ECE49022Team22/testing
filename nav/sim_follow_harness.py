"""Run the real follow.py, in real time, against the simulator instead of the robot: fake LiDAR, IMU, STM32 and
hold-to-run button, driven by sim_local_nav's robot model and world. It checks the follow.py wiring (frames,
signs, the planner thread, guard, back-up, logging) that sim_local_nav.py doesn't, because that one has its own
copy of the control loop.

    python3 nav/sim_follow_harness.py trash_can --model casters --speed 0.6 --avoid
    python3 nav/sim_follow_harness.py bike_rack --plot rack.png --avoid
    python3 nav/sim_follow_harness.py trash_can                 # without --avoid: today's follow.py

It uses follow.py's `local` mode (no GPS: the path is in metres from the start pose), so only straight-route
scenarios apply. Logs go to a temporary folder, not nav/logs.
"""
import argparse
import math
import os
import sys
import tempfile
import threading
import time
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "motor_cal"))
import sim_local_nav as sim  # noqa: E402


class Plant(threading.Thread):
    """The simulated robot + world, stepped at 100 Hz against the wall clock."""

    def __init__(self, scn, model, speed, seed=1):
        super().__init__(daemon=True)
        self.rng = np.random.default_rng(seed)
        self.world = sim.scenario(scn, speed)
        self.robot = sim.Robot(model, (0.0, 0.0, 0.0), self.rng)
        self.lidar = sim.Lidar(self.rng)
        self.scan, self.scan_t = None, 0.0
        self.imu_bias_est = 0.0
        self.yaw, self.gz, self.imu_t = 0.0, 0.0, 0.0
        self.t0 = time.monotonic()
        self.t = 0.0
        self.k = 0
        self.lock = threading.Lock()
        self.trace = []
        self.stop = threading.Event()

    def run(self):
        nxt = time.monotonic()
        while not self.stop.is_set():
            now = time.monotonic()
            while nxt <= now:                                  # catch up if a step ran late
                with self.lock:
                    self.robot.step()
                    pose = (self.robot.x, self.robot.y, self.robot.h)
                    sc = self.lidar.slice(self.world, self.t, pose, self.k)
                    self.k = (self.k + 1) % 10
                    g = self.robot.gz() - self.imu_bias_est
                    self.yaw += g * sim.DT
                    self.gz, self.imu_t = g, time.monotonic()
                    self.t += sim.DT
                if sc is not None:
                    self.scan, self.scan_t = sc, time.monotonic()
                if self.k == 0:
                    self.trace.append((self.t, *pose))
                nxt += sim.DT
            time.sleep(max(0.0, nxt - time.monotonic()))


def fake_modules(plant):
    rd = types.ModuleType("robot_drive")
    rd.WHEEL_C = sim.WHEEL_C
    rd.STOP_FILE = os.path.join(tempfile.mkdtemp(), "STOP")
    rd.rpm_for = lambda v: v / rd.WHEEL_C * 60

    class Lidar:
        def __init__(self):
            self.scan, self.t = None, 0.0

        def start(self):
            def loop():
                last = 0.0
                while True:
                    if plant.scan_t != last:
                        last = plant.scan_t
                        self.scan, self.t = plant.scan, plant.scan_t
                    time.sleep(0.005)
            threading.Thread(target=loop, daemon=True).start()

    class Imu:
        def __init__(self):
            self._bias = 0.0

        def start(self):
            pass

        gz = property(lambda self: plant.gz)
        yaw = property(lambda self: plant.yaw, lambda self, v: setattr(plant, "yaw", v))
        t = property(lambda self: plant.imu_t)

        @property
        def bias(self):
            return plant.imu_bias_est

        @bias.setter
        def bias(self, v):
            plant.imu_bias_est = v

        def close(self):
            pass

    class Ser:
        def write(self, b):
            pass

    class Stm32:
        def __init__(self, *a):
            self.ser, self.flags = Ser(), ""
            self.cmds = []

        @property
        def row(self):
            return [0.0] * 10

        @property
        def t(self):
            return time.monotonic()

        def wheels(self):
            k = 60 / (rd.WHEEL_C * sim.WHEEL_SCALE)
            return (plant.robot.vl * k, plant.robot.vr * k), (0, 0)

        def drive(self, left_rpm, right_rpm):
            c = rd.WHEEL_C * sim.WHEEL_SCALE / 60
            with plant.lock:
                plant.robot.cmd = (left_rpm * c, right_rpm * c)

        def stop(self):
            self.drive(0.0, 0.0)

        def close(self):
            self.drive(0.0, 0.0)

    rd.Lidar, rd.Imu, rd.Stm32 = Lidar, Imu, Stm32
    nt = types.ModuleType("ntrip_rtk")

    class Receiver:
        def __init__(self, *a):
            self.gga = b""
    nt.Receiver = Receiver
    nt.ntrip = lambda *a: None
    return rd, nt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=[s for s in sim.SCENARIOS if s not in ("corner_obstacle", "campus_mix",
                                                                              "osm_offset", "gps_jump")])
    ap.add_argument("--model", default="casters", choices=("taped", "casters"))
    ap.add_argument("--speed", type=float, default=0.6)
    ap.add_argument("--avoid", action="store_true")
    ap.add_argument("--length", type=float, default=30.0)
    ap.add_argument("--plot")
    ap.add_argument("--max-s", type=float, default=150)
    a = ap.parse_args()

    plant = Plant(a.scenario, a.model, a.speed)
    rd, nt = fake_modules(plant)
    sys.modules["robot_drive"], sys.modules["ntrip_rtk"] = rd, nt
    import follow
    tmp = tempfile.mkdtemp(prefix="follow_sim_")
    follow.HERE = tmp                                          # logs go here, not into nav/logs

    def fake_page(port, st):
        def hold():
            while True:
                st["hold_t"] = time.monotonic()
                time.sleep(0.1)
        threading.Thread(target=hold, daemon=True).start()
        return None
    follow.start_page = fake_page
    follow.page_urls = lambda port: ["(simulated)"]
    sys.argv = ["follow.py", "local", "--points", f"0,0 {a.length:g},0", "--speed", str(a.speed), "--no-video",
                "--no-ntrip", "--max-s", str(a.max_s)] + (["--avoid"] if a.avoid else [])
    plant.start()
    t0 = time.monotonic()
    try:
        follow.main()
    finally:
        plant.stop.set()
    wall = time.monotonic() - t0
    import glob
    import json
    logf = sorted(glob.glob(os.path.join(tmp, "logs", "follow_local_*.json")))[-1]
    lg = json.load(open(logf))
    tr = np.array(plant.trace)
    cl = [sim.rect_clearance((x, y, h), np.vstack((plant.world.solid, plant.world.dyn(t)))) for t, x, y, h in tr[::5]]
    log = lg["log"]
    dt = np.diff([r["t"] for r in log])
    stops = sum(1 for r in log if r["pause"] and r["pause"] != "button not held")
    print(f"\n=== {a.scenario} | {a.model} {a.speed} m/s | {'--avoid' if a.avoid else 'today (no --avoid)'} ===")
    print(f"follow.py stopped: {lg['reason']} after {log[-1]['t']:.1f} s (wall {wall:.0f} s), "
          f"true end x {tr[-1, 1]:.2f} m of {a.length:g}")
    print(f"min clearance to obstacles (true, chassis rectangle): {min(cl):+.3f} m; max |y| {np.abs(tr[:, 2]).max():.2f} m")
    print(f"control loop: {len(log)} ticks, interval median {np.median(dt) * 1e3:.0f} ms, 99 % {np.percentile(dt, 99) * 1e3:.0f} ms, "
          f"max {dt.max() * 1e3:.0f} ms; paused ticks {stops}")
    if a.avoid:
        ok = sum(1 for r in log if r.get("nav_ok"))
        ms = [r["nav_ms"] for r in log if r.get("nav_ms") is not None]
        print(f"planner: ok on {ok}/{len(log)} ticks, plan time median {np.median(ms):.1f} ms, max {max(ms):.1f} ms, "
              f"backing-up ticks {sum(1 for r in log if r.get('back', 0) < 0)}, {len(lg.get('nav_paths', []))} plans logged")
        whys = {}
        for r in log:
            if r["pause"] and r["pause"] != "button not held":
                whys[r["pause"].split(':')[0]] = whys.get(r["pause"].split(':')[0], 0) + 1
        if whys:
            print("pauses:", whys)
    if a.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(14, 4))
        w = plant.world
        nc, ns = w.n_fg
        for x_, y_, r_ in w.circles[:nc]:
            ax.add_patch(plt.Circle((x_, y_), r_, color="k"))
        for x1, y1, x2, y2 in w.segs[:ns]:
            ax.plot([x1, x2], [y1, y2], "k-", lw=2)
        ax.plot([0, a.length], [0, 0], "b--", lw=1, label="path")
        ax.plot(tr[:, 1], tr[:, 2], "-", color="#d0442c", lw=1.5, label="robot (truth)")
        fx = [r["x"] for r in log if r["phase"] == "follow"]
        fy = [r["y"] for r in log if r["phase"] == "follow"]
        ax.plot(fx, fy, ":", color="#555", lw=1, label="follow.py's own pose")
        for tp, pts in lg.get("nav_paths", [])[::3]:
            p = np.array(pts)
            ax.plot(p[:, 0], p[:, 1], "-", color="#2a9d4a", lw=0.6, alpha=0.6)
        ax.set_aspect("equal")
        ax.set_xlim(-1, a.length + 1)
        ax.set_ylim(-2.2, 2.2)
        ax.legend(fontsize=8, loc="upper right")
        ax.set_title(f"follow.py (real code) vs simulator: {a.scenario}, {a.model} {a.speed} m/s, "
                     f"{'--avoid' if a.avoid else 'no --avoid'}: {lg['reason']}, min clearance {min(cl):+.2f} m")
        plt.tight_layout()
        plt.savefig(a.plot, dpi=90)


if __name__ == "__main__":
    main()
