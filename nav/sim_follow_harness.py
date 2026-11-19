"""Run the real follow.py, in real time, against the simulator instead of the robot: fake LiDAR, IMU, STM32 and
hold-to-run button, driven by sim_local_nav's robot model and world. It checks the follow.py wiring (frames,
signs, the planner thread, guard, back-up, logging) that sim_local_nav.py doesn't, because that one has its own
copy of the control loop.

    python3 nav/sim_follow_harness.py trash_can --model casters --speed 0.6 --avoid
    python3 nav/sim_follow_harness.py bike_rack --plot rack.png --avoid
    python3 nav/sim_follow_harness.py trash_can                 # without --avoid: today's follow.py

    python3 nav/sim_follow_harness.py clear --app --length 24  # follow.py --app: a whole delivery via fake_app.py

Without --app it uses follow.py's `local` mode (no GPS: the path is in metres from the start pose), so only straight-route
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


# Harness-only scenarios for what a flat 2D LiDAR gets wrong (16 Nov MSEE run):
#   kerb          a kerb across the left of the walk at x = 12 m, below the scan plane: invisible, but the robot
#                 can't drive through it (wheels stall); the way round is on the right (y < -0.6)
#   slope         the walk rises at x = 14 m: from x = 9.5 to 15 the beams ahead hit the ground ~4.5 m out, a "wall"
#                 that moves with the robot
#   person_ahead  someone steps onto the route 2.3 m in front of the robot (when it passes x = 9.7) and stays
EXTRA = ("kerb", "slope", "person_ahead")


class Plant(threading.Thread):
    """The simulated robot + world, stepped at 100 Hz against the wall clock."""

    def __init__(self, scn, model, speed, seed=1):
        super().__init__(daemon=True)
        self.rng = np.random.default_rng(seed)
        self.scn = scn
        self.world = sim.scenario("clear" if scn in EXTRA else scn, speed)
        self.hidden = np.zeros((0, 3))
        self.blocked_steps = 0
        if scn == "kerb":
            yy = np.arange(-0.6, 1.6, 0.02)
            self.hidden = np.column_stack((np.full(len(yy), 12.0), yy, np.zeros(len(yy))))
        if scn == "person_ahead":
            legs = sim.ped((12.0, 0.1), (1.0, 0.0), stand=(0.0, 1e9))
            self.seen = False

            def person(t):
                self.seen = self.seen or self.robot.x >= 9.7
                return legs(t) if self.seen else []
            self.world.peds.append(person)
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
                    before = (self.robot.x, self.robot.y, self.robot.h)
                    self.robot.step()
                    if len(self.hidden) and sim.rect_clearance((self.robot.x, self.robot.y, self.robot.h), self.hidden) < 0:
                        self.robot.x, self.robot.y, self.robot.h = before        # against the kerb: wheels stall
                        self.robot.vl = self.robot.vr = self.robot.r = 0.0
                        self.blocked_steps += 1
                    pose = (self.robot.x, self.robot.y, self.robot.h)
                    sc = self.lidar.slice(self.world, self.t, pose, self.k)
                    if sc is not None and self.scn == "slope" and 9.5 <= self.robot.x <= 15.0:
                        f = sim.ln.FRONT_DEG
                        sc = [(a_, min(d_, 4500.0 + self.rng.normal(0, 30)) if abs((f - a_ + 180) % 360 - 180) < 50
                               else d_, q_) for a_, d_, q_ in sc]
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


LAT0, LON0 = 40.4286, -86.9115                              # sim origin (BHEE courtyard); x = east, y = north


def sim_to_ll(x, y):
    k = math.cos(math.radians(LAT0))
    return LAT0 + math.degrees(y / 6378137.0), LON0 + math.degrees(x / (6378137.0 * k))


def fake_gps(plant, rng):
    """ntrip_rtk.Receiver stand-in: RTK-fixed GGA of the simulated robot at 5 Hz, 1 cm noise."""
    class Receiver:
        def __init__(self, *a):
            pass

        @property
        def gga(self):
            k = int(time.monotonic() * 5)
            if getattr(self, "_k", None) != k:
                self._k = k
                with plant.lock:
                    x, y = plant.robot.x + rng.normal(0, 0.01), plant.robot.y + rng.normal(0, 0.01)
                lat, lon = sim_to_ll(x, y)
                self._s = (f"$GNGGA,{k % 100000:06d}.00,{int(lat):02d}{(lat % 1) * 60:010.7f},N,"
                           f"{int(-lon):03d}{(-lon % 1) * 60:010.7f},W,4,24,0.6,190.0,M,-33.0,M,1.0,0000*00").encode()
            return self._s
    return Receiver


def run_app(a, plant, rd, nt):
    """follow.py --app against the simulator and fake_app.py: a full delivery, with a vendor and a customer pressing
    the buttons, an unlock sent while driving (must be refused) and a link outage on the second leg (must stop it)."""
    import json
    from fake_app import FakeApp
    nt.Receiver = fake_gps(plant, np.random.default_rng(7))
    sys.modules["robot_drive"], sys.modules["ntrip_rtk"] = rd, nt
    import follow
    tmp = tempfile.mkdtemp(prefix="follow_app_")
    follow.HERE = tmp
    app = FakeApp(poll_seconds=1)
    os.environ["ROBOT_API_TOKEN"] = "test"
    pick, dest = a.length * 0.45, a.length
    ll = lambda x, y: [round(v, 8) for v in sim_to_ll(x, y)[::-1]]              # [lon, lat], as the app sends
    job = {"deliveryId": "sim1", "profile": "foot-walking",
           "pickup": dict(zip(("lat", "lon"), sim_to_ll(pick, 0)), name="sim pickup"),
           "destination": dict(zip(("lat", "lon"), sim_to_ll(dest, 0)), label="sim destination"),
           "legs": [{"to": "pickup", "polyline": [ll(0, 0), ll(pick / 2, 0), ll(pick, 0)]},
                    {"to": "destination", "polyline": [ll(pick, 0), ll(dest, 0)]}]}
    ev = {"moved_before_enable": 0.0, "enable_t": None, "outage": None, "stops": {}, "restart": None}
    cur = {"st": None, "run": 1}
    t0 = time.monotonic()

    def ops():
        app.add("delivery", job)                                       # arrives while driving is still disabled
        time.sleep(6)
        with plant.lock:
            ev["moved_before_enable"] = math.hypot(plant.robot.x, plant.robot.y)
        cur["st"]["enabled"], ev["enable_t"] = True, time.monotonic() - t0
        seen = set()
        while True:
            st = cur["st"]
            st["hold_t"] = time.monotonic()
            tel = app.telemetry()
            state = tel[-1]["state"] if tel else None
            with plant.lock:
                x = plant.robot.x
            if state == "EN_ROUTE_PICKUP" and x > 3 and "early" not in seen:
                seen.add("early")
                app.add("unlock", {"deliveryId": "sim1"}, cid="unlock-while-driving")
            if state in ("AWAITING_LOAD", "ARRIVED") and state not in seen:
                seen.add(state)
                with plant.lock:
                    ev["stops"][state] = (plant.robot.x, plant.robot.y)
                time.sleep(2)
                app.add("unlock", {"deliveryId": "sim1"})
                time.sleep(2)
                app.add("lock", {"deliveryId": "sim1"})
            if state == "EN_ROUTE_DESTINATION" and x > pick + 3 and a.restart and "restart" not in seen:
                seen.add("restart")                                # follow.py dies mid-leg; the service restarts it
                open(rd.STOP_FILE, "w").close()
                while cur["run"] == 1:
                    time.sleep(0.05)
                with plant.lock:
                    x0 = plant.robot.x
                time.sleep(8)                                      # new run: driving must be disabled again
                with plant.lock:
                    ev["restart"] = (x0, plant.robot.x - x0)
                cur["st"]["enabled"] = True
                continue
            if state == "EN_ROUTE_DESTINATION" and x > pick + 3 and not a.restart and "outage" not in seen:
                seen.add("outage")
                app.offline, ev["outage"] = True, (time.monotonic() - t0, x)
                time.sleep(a.link_timeout + 4)
                app.offline = False
            if state == "IDLE" and "ARRIVED" in seen:
                time.sleep(1)
                cur["done"] = True
                open(rd.STOP_FILE, "w").close()
                return
            time.sleep(0.1)

    def fake_page(port, st):
        cur["st"] = st
        if cur.get("ops") is None:
            cur["ops"] = threading.Thread(target=ops, daemon=True)
            cur["ops"].start()
        return None
    follow.start_page = fake_page
    follow.page_urls = lambda port: ["(simulated)"]
    sys.argv = ["follow.py", "--app", "--app-url", app.url, "--speed", str(a.speed), "--no-video", "--no-ntrip",
                "--max-s", str(a.max_s), "--link-timeout", str(a.link_timeout), "--log-every", "15",
                "--state-file", os.path.join(tmp, "delivery.json")] + (["--avoid"] if a.avoid else []) + a.flags.split()
    argv = list(sys.argv)
    plant.start()
    try:
        follow.main()
        if a.restart and not cur.get("done"):                          # the "service" starts it again
            os.remove(rd.STOP_FILE)
            sys.argv = argv
            cur["run"] = 2
            print("\n--- restarting follow.py (as the boot service would) ---\n", flush=True)
            follow.main()
    finally:
        plant.stop.set()
        time.sleep(1.5)
    import glob
    files = sorted(glob.glob(os.path.join(tmp, "logs", "follow_app_*.json")))
    parts = [json.load(open(f)) for f in files if "_part" in f]
    lg = json.load(open([f for f in files if "_part" not in f][-1]))
    lg["log"] = [r for p in parts for r in p["log"]] + lg["log"]                 # whole run, parts first
    lg["app_events"] = [e for p in parts for e in p["app_events"]] + lg["app_events"]
    states = [t["state"] for t in app.telemetry()]
    print(f"\n=== follow.py --app | {a.model} {a.speed} m/s | {'--avoid' if a.avoid else 'no --avoid'} ===")
    print(f"stopped: {lg['reason']}; telemetry states: {' -> '.join(s for i, s in enumerate(states) if i == 0 or s != states[i - 1])}")
    print(f"moved before 'Enable driving' (delivery already received): {ev['moved_before_enable']:.3f} m")
    for st_, (x, y) in ev["stops"].items():
        want = pick if st_ == "AWAITING_LOAD" else dest
        print(f"{st_}: robot at x {x:.2f}, y {y:+.2f} m; stop point x {want:.1f} m -> {math.hypot(x - want, y):.2f} m away")
    for ack in app.acks():
        print(f"ack {ack['type']:8s} {ack['id'][:20]:20s} ok={ack['ok']} {ack.get('error') or ack.get('result')}")
    if ev["restart"]:
        print(f"restart mid-leg at x {ev['restart'][0]:.1f} m: moved {ev['restart'][1]:.3f} m before driving was "
              f"re-enabled; parts written: {len(parts)}")
    if ev["outage"]:
        t_out, x_out = ev["outage"]
        lost = [r for r in lg["log"] if (r["pause"] or "").startswith("app link lost")]
        print(f"link outage from t={t_out:.0f} s at x {x_out:.1f} m: paused 'app link lost' for {len(lost) * 0.05:.1f} s, "
              f"speed while paused max {max((r['v'] for r in lost), default=float('nan')):.2f} m/s")
    print(f"app events: {len(lg['app_events'])}, uplinked notes: {len(app.order)}")
    app.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=[s for s in sim.SCENARIOS if s not in ("corner_obstacle", "campus_mix",
                                                                              "osm_offset", "gps_jump")] + list(EXTRA))
    ap.add_argument("--flags", default="", help="extra follow.py flags, e.g. \"--no-creep\"")
    ap.add_argument("--model", default="casters", choices=("taped", "casters"))
    ap.add_argument("--speed", type=float, default=0.6)
    ap.add_argument("--avoid", action="store_true")
    ap.add_argument("--length", type=float, default=30.0)
    ap.add_argument("--plot")
    ap.add_argument("--max-s", type=float, default=150)
    ap.add_argument("--app", action="store_true",
                    help="run follow.py --app against fake_app.py: one full delivery (use the 'clear' scenario)")
    ap.add_argument("--restart", action="store_true", help="--app: restart follow.py mid-leg instead of the outage test")
    ap.add_argument("--link-timeout", type=float, default=3.0, help="--app: follow.py's --link-timeout for the outage test")
    a = ap.parse_args()

    plant = Plant(a.scenario, a.model, a.speed)
    rd, nt = fake_modules(plant)
    if a.app:
        return run_app(a, plant, rd, nt)
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
                "--no-ntrip", "--max-s", str(a.max_s)] + (["--avoid"] if a.avoid else []) + a.flags.split()
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
    if len(plant.hidden):
        print(f"pushing against the invisible kerb: {plant.blocked_steps * sim.DT:.1f} s")
    print(f"time to cover the path: {next((t for t, x, y, h in tr if x >= a.length - 0.5), float('nan')):.1f} s (sim time)")
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
