#!/usr/bin/env python3
"""Run every sensor app at once, the way the robot does, and show it live in a browser.

  python3 run_demo.py                    # optimized: the final benchmarked system (bench/final.toml)
  python3 run_demo.py --profile cpu      # best setup before the AI HAT: YOLO on the CPU (NCNN)
  python3 run_demo.py --profile baseline # how it started: no pinning, no RT, PyTorch YOLO, queued camera
  python3 run_demo.py --only imu gps     # a subset
  python3 run_demo.py --browser          # also open the dashboard on the Pi's screen (pinned to core 0)

Then open http://<pi>:8090/ (on the Pi: http://localhost:8090/). Ctrl-C stops everything.

Each sensor is its own process, pinned and prioritised by the profile, and restarted if it dies.
The motor worker holds the STM32 at 0 RPM unless --motor-rpm is given (it only ever sends a target RPM).
"""
import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
SENSOR_PY = os.path.join(HOME, "testing/.venv/bin/python")
VISION_PY = os.path.join(HOME, "stop-sign-eval/.venv/bin/python")
SYS_PY = "/usr/bin/python3"
RT_ENV = {"RT_TIMERSLACK_NS": "1", "RT_MLOCK": "1"}

# name: (python, script, args); cpus / rt_prio / env come from the profile
WORKERS = {
    "imu": (SENSOR_PY, "d_imu.py", []),
    "lidar": (SENSOR_PY, "d_lidar.py", []),
    "gps": (SENSOR_PY, "d_gps.py", []),
    "vision": (VISION_PY, "d_vision.py", []),
    "cell": (SYS_PY, "d_cell.py", []),
    "motor": (SENSOR_PY, "d_motor.py", []),
}

# Same layout and priorities as bench/final.toml. RT priorities stay below 50 so the kernel's IRQ
# threads (SCHED_FIFO 50) that deliver the sensors' interrupts on core 1 always run first.
PROFILES = {
    "optimized": {
        "about": "Final system: sensors on isolated core 1 at RT priority, vision on cores 2-3 on the AI HAT+",
        "roles": {"0": "OS, hub, cellular", "1": "sensors (isolated, real-time)", "2": "vision", "3": "vision"},
        "hub": {"cpus": "0"},
        "imu": {"cpus": "1", "rt_prio": 49, "env": RT_ENV},
        "lidar": {"cpus": "1", "rt_prio": 47, "env": RT_ENV},
        "gps": {"cpus": "1", "rt_prio": 46, "env": RT_ENV},
        "motor": {"cpus": "1", "rt_prio": 48, "env": RT_ENV},
        "vision": {"cpus": "2,3", "args": ["--backend", "hailo", "--camera", "latest"]},
        "cell": {"cpus": "0"},
    },
    "cpu": {
        "about": "Best setup before the AI HAT+: same core split and RT priorities, YOLO on the CPU (NCNN)",
        "roles": {"0": "OS, hub, cellular", "1": "sensors (isolated, real-time)", "2": "vision (CPU YOLO)", "3": "vision (CPU YOLO)"},
        "hub": {"cpus": "0"},
        "imu": {"cpus": "1", "rt_prio": 49, "env": RT_ENV},
        "lidar": {"cpus": "1", "rt_prio": 47, "env": RT_ENV},
        "gps": {"cpus": "1", "rt_prio": 46, "env": RT_ENV},
        "motor": {"cpus": "1", "rt_prio": 48, "env": RT_ENV},
        "vision": {"cpus": "2,3", "args": ["--backend", "ncnn", "--camera", "latest"], "env": {"OMP_WAIT_POLICY": "passive"}},
        "cell": {"cpus": "0"},
    },
    "baseline": {
        "about": "How it started: no pinning, no RT priority, PyTorch YOLO on the CPU, queued camera frames",
        "roles": {"0": "shared", "1": "shared (isolcpus is on, so unpinned work avoids it)", "2": "shared", "3": "shared"},
        "hub": {},
        "imu": {}, "lidar": {}, "gps": {}, "motor": {},
        "vision": {"args": ["--backend", "torch", "--camera", "queued"]},
        "cell": {},
    },
}


def command(py, script, args, spec):
    cmd = [py, "-u", os.path.join(HERE, script)] + args + spec.get("args", [])
    if spec.get("rt_prio"):
        cmd = ["chrt", "-f", str(spec["rt_prio"])] + cmd
    if spec.get("cpus") is not None:
        cmd = ["taskset", "-c", spec["cpus"]] + cmd
    return cmd


class Proc:
    def __init__(self, name, cmd, env, logdir):
        self.name, self.cmd, self.env, self.logdir = name, cmd, env, logdir
        self.p, self.restarts, self.next_start = None, 0, 0.0

    def start(self):
        log = open(os.path.join(self.logdir, f"{self.name}.log"), "a")
        log.write(f"\n=== {time.strftime('%H:%M:%S')} $ {shlex.join(self.cmd)}\n")
        log.flush()
        self.p = subprocess.Popen(self.cmd, cwd=HERE, env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        log.close()

    def poll(self):
        """Restart a worker that exited (after 3 s, so an unplugged sensor doesn't spin)."""
        if self.p is not None and self.p.poll() is not None:
            print(f"  {self.name} exited ({self.p.returncode}); restarting in 3 s (logs/{self.name}.log)", flush=True)
            self.p, self.next_start = None, time.time() + 3
            self.restarts += 1
        if self.p is None and time.time() >= self.next_start:
            self.start()

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.send_signal(signal.SIGINT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="optimized")
    ap.add_argument("--only", nargs="+", choices=sorted(WORKERS), help="start just these workers")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--motor-port", default="/dev/ttyUSB0",
                    help="serial port to the STM32: the USB-serial adapter today, a direct UART later (e.g. /dev/ttyAMA3)")
    ap.add_argument("--motor-rpm", type=float, default=0.0,
                    help="target RPM the motor worker holds (default 0: the motor stays still)")
    ap.add_argument("--browser", action="store_true",
                    help="open the dashboard in a Chromium window on core 0 at low priority (a browser on the "
                         "vision cores slows detection; on core 0 it only competes with the OS)")
    a = ap.parse_args()
    prof = PROFILES[a.profile]
    # A previous demo that's still shutting down keeps the ports, and the new hub/video would then
    # retry behind it while the old hub keeps answering. Wait for them, or say who has them.
    for _ in range(20):
        busy = []
        for port in (a.port, 8091):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    busy.append(port)
        if not busy:
            break
        time.sleep(0.5)
    else:
        sys.exit(f"ports {busy} are still in use: another demo is running (stop it with Ctrl-C, or: pkill -INT -f run_demo.py)")
    logdir = os.path.join(HERE, "logs")
    os.makedirs(logdir, exist_ok=True)

    hub_cmd = command(SYS_PY, "hub.py", ["--port", str(a.port), "--profile", a.profile,
                                         "--roles", json.dumps({"about": prof["about"], **prof["roles"]})], prof["hub"])
    procs = [Proc("hub", hub_cmd, dict(os.environ), logdir)]
    for name, (py, script, args) in WORKERS.items():
        if a.only and name not in a.only:
            continue
        spec = dict(prof[name])
        if name == "motor":
            spec["args"] = spec.get("args", []) + ["--rpm", f"{a.motor_rpm:g}", "--port", a.motor_port]
        procs.append(Proc(name, command(py, script, args, spec), dict(os.environ, **spec.get("env", {})), logdir))

    print(f"profile: {a.profile} - {prof['about']}")
    for p in procs:
        print(f"  {p.name:7s} {shlex.join(p.cmd)}")
    print(f"\ndashboard: http://localhost:{a.port}/   (from another machine: http://<pi-address>:{a.port}/)")
    print(f"motor / STM32: target {a.motor_rpm:g} RPM" + ("  <-- the motor WILL turn" if a.motor_rpm else " (motor stays still)"))
    print("Ctrl-C to stop.\n", flush=True)

    browser = None
    if a.browser:
        time.sleep(2)                                    # let the hub come up first
        profile_dir = os.path.join(HOME, ".cache", "sensor-demo-chromium")   # separate from the user's own browser
        browser = subprocess.Popen(["taskset", "-c", "0", "nice", "-n", "10", "chromium", f"--user-data-dir={profile_dir}",
                                    "--no-first-run", f"--app=http://localhost:{a.port}/"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(1))
    try:
        while not stopping:
            for p in procs:
                p.poll()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("\nstopping...", flush=True)
    if browser and browser.poll() is None:
        browser.terminate()
    for p in procs:
        p.stop()
    deadline = time.time() + 8
    for p in procs:
        if p.p:
            try:
                p.p.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
