#!/usr/bin/env python3
"""Demo hub: collects the workers' datagrams, samples the system, serves the dashboard.

  http://<pi>:8090/          the dashboard (static/)
  http://<pi>:8090/events    Server-Sent Events: the whole state, 10x per second
  http://<pi>:8090/state     one JSON snapshot

Runs on core 0 at normal priority, away from the sensors. Read-only: it has no endpoints that
command anything. (The motor worker, d_motor.py, is the only process that talks to the STM32.)
"""
import argparse
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
CLK_TCK = os.sysconf("SC_CLK_TCK")
POLICY = {0: "normal", 1: "FIFO", 2: "RR", 3: "batch", 5: "idle"}

# Streams shown in the deadline panel: (worker, stats key, budget ms, what the budget means)
DEADLINES = [
    ("imu", "int_latency_ms", 10.0, "IMU interrupt"),          # BNO085 stops signalling after ~10 ms
    ("imu", "period_ms", 15.0, "IMU sample period"),          # samples every 10 ms; late if > 15 ms
    ("lidar", "excess_ms", 10.0, "LiDAR delivery"),            # above the drift-corrected best case
    ("gps", "gga_jitter_ms", 20.0, "GPS fix timing"),          # vs the 5 Hz grid
    ("vision", "e2e_ms", 150.0, "Stop sign detection"),        # camera capture -> detection
    ("motor", "cmd_rtt_ms", 20.0, "Motor command ack"),        # target RPM sent -> STM32 "OK"
]
HISTORY_KEYS = [(w, k) for w, k, _, _ in DEADLINES] + [("vision", "fps")]
HISTORY_LEN = 240                       # 2 minutes of 0.5 s windows
WARMUP_S = 5.0                          # deadline accounting starts this long after a worker (re)starts


class State:
    def __init__(self, profile, roles):
        self.lock = threading.Lock()
        self.started = time.time()
        self.profile, self.roles = profile, roles
        self.workers = {}
        self.history = {f"{w}.{k}": [] for w, k in HISTORY_KEYS}
        self.deadlines = {f"{w}.{k}": {"worker": w, "key": k, "budget": b, "label": lab, "worst": None,
                                       "windows": 0, "over": 0} for w, k, b, lab in DEADLINES}
        self.system = {}

    def ingest(self, msg):
        src, kind = msg.get("src"), msg.get("kind")
        with self.lock:
            w = self.workers.setdefault(src, {})
            if w.get("pid") != msg.get("pid"):             # new or restarted worker process
                w["since"] = time.time()
            w["pid"], w["seen"] = msg.get("pid"), time.time()
            w[kind] = msg
            if kind != "stats":
                return
            # Skip a worker's first seconds for deadline accounting: start-up (models loading, every
            # worker launching at once, memory being locked) isn't steady-state latency.
            warm = time.time() - w["since"] >= WARMUP_S
            for key in [k for ww, k in HISTORY_KEYS if ww == src]:
                v = msg.get(key)
                hist = self.history[f"{src}.{key}"]
                if isinstance(v, dict):
                    hist.append([msg["t"], v["p99"], v["max"]])
                elif isinstance(v, (int, float)):
                    hist.append([msg["t"], v, v])
                del hist[:-HISTORY_LEN]
                d = self.deadlines.get(f"{src}.{key}")
                if d and warm and isinstance(v, dict):
                    d["windows"] += 1
                    d["over"] += v["max"] > d["budget"]
                    d["worst"] = v["max"] if d["worst"] is None else max(d["worst"], v["max"])

    def snapshot(self):
        with self.lock:
            return json.dumps({"now": time.time(), "started": self.started, "profile": self.profile,
                               "roles": self.roles, "workers": self.workers, "history": self.history,
                               "deadlines": list(self.deadlines.values()), "system": self.system},
                              separators=(",", ":"))


def udp_loop(state, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    s.bind(("127.0.0.1", port))
    while True:
        data, _ = s.recvfrom(65535)
        try:
            state.ingest(json.loads(data))
        except (ValueError, KeyError):
            pass


def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                name, *v = line.split()
                v = list(map(int, v))
                out[int(name[3:])] = (sum(v), v[3] + v[4])
    return out


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def proc_info(pid):
    """Core, policy/priority, CPU time and preemptions for one process (summed over its threads)."""
    try:
        fields = read(f"/proc/{pid}/stat").rsplit(")", 1)[1].split()
        comm = read(f"/proc/{pid}/comm")
        allowed = next(l.split()[1] for l in read(f"/proc/{pid}/status").splitlines() if l.startswith("Cpus_allowed_list"))
        cpu, invol, cores = 0, 0, set()
        for tid in os.listdir(f"/proc/{pid}/task"):
            tf = (read(f"/proc/{pid}/task/{tid}/stat") or ")").rsplit(")", 1)[1].split()
            if len(tf) > 36:
                cpu += int(tf[11]) + int(tf[12])
                cores.add(int(tf[36]))
            st = read(f"/proc/{pid}/task/{tid}/status") or ""
            invol += sum(int(l.split()[1]) for l in st.splitlines() if l.startswith("nonvoluntary_ctxt_switches"))
        return {"comm": comm, "allowed": allowed, "cores": sorted(cores), "policy": POLICY.get(int(fields[38]), fields[38]),
                "prio": int(fields[37]), "cpu_s": cpu / CLK_TCK, "invol": invol, "threads": len(os.listdir(f"/proc/{pid}/task"))}
    except (OSError, IndexError, StopIteration, ValueError, TypeError):
        return None


def who_has_open(dev):
    """PIDs (of this user) holding `dev` open. Looks at /proc only; never opens the device."""
    try:
        target = os.path.realpath(dev)
    except OSError:
        return []
    pids = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.path.realpath(f"/proc/{pid}/fd/{fd}") == target:
                    pids.append({"pid": int(pid), "comm": read(f"/proc/{pid}/comm"),
                                 "cmd": (read(f"/proc/{pid}/cmdline") or "").replace("\0", " ").strip()[:120]})
                    break
        except OSError:
            continue
    return pids


def system_loop(state, period=0.5):
    prev = cpu_times()
    prev_proc, i = {}, 0
    while True:
        time.sleep(period)
        cur = cpu_times()
        cores = []
        for c in sorted(cur):
            dt, di = cur[c][0] - prev[c][0], cur[c][1] - prev[c][1]
            cores.append({"core": c, "util": round(100 * (dt - di) / dt, 1) if dt else 0.0})
        prev = cur
        sysd = {"cores": cores,
                "freq_mhz": int(read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "0")) // 1000,
                "governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
                "temp_c": int(read("/sys/class/thermal/thermal_zone0/temp", "0")) / 1000,
                "isolated": read("/sys/devices/system/cpu/isolated", "")}
        with state.lock:
            pids = {name: w.get("pid") for name, w in state.workers.items()}
            old = state.system
        pids["hub"] = os.getpid()
        procs, t = [], time.monotonic()
        for name, pid in sorted(pids.items()):
            info = pid and proc_info(pid)
            if not info:
                continue
            p = prev_proc.get(pid)
            if p:
                info["cpu_pct"] = round(100 * (info["cpu_s"] - p["cpu_s"]) / (t - p["t"]), 1)
                info["preempt_s"] = round((info["invol"] - p["invol"]) / (t - p["t"]))
            prev_proc[pid] = {"cpu_s": info["cpu_s"], "invol": info["invol"], "t": t}
            procs.append({"name": name, "pid": pid, **info})
        sysd["procs"] = procs
        if i % 4 == 0:                       # every 2 s: firmware queries and the motor port
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout
            sysd["throttled"] = out.strip().split("=")[-1] if out else None
            adc = subprocess.run(["vcgencmd", "pmic_read_adc"], capture_output=True, text=True).stdout
            for line in adc.splitlines():
                if "EXT5V_V" in line:
                    sysd["ext5v_v"] = round(float(line.split("=")[1].rstrip("V")), 2)
                if "VDD_CORE_A" in line:
                    sysd["vdd_core_a"] = round(float(line.split("=")[1].rstrip("A")), 2)
            sysd["motor"] = {"present": os.path.exists("/dev/ttyUSB0"), "holders": who_has_open("/dev/ttyUSB0")}
        else:
            for k in ("throttled", "ext5v_v", "vdd_core_a", "motor"):
                if k in old:
                    sysd[k] = old[k]
        with state.lock:
            state.system = sysd
        i += 1


def make_handler(state):
    types = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    while True:
                        self.wfile.write(b"data: " + state.snapshot().encode() + b"\n\n")
                        self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    return
            if path == "/state":
                return self._send(state.snapshot().encode(), "application/json")
            name = "index.html" if path == "/" else path.lstrip("/")
            full = os.path.realpath(os.path.join(STATIC, name))
            if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
                return self._send(b"not found", "text/plain", 404)
            with open(full, "rb") as f:
                self._send(f.read(), types.get(os.path.splitext(full)[1], "application/octet-stream"))

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--bus-port", type=int, default=8765)
    ap.add_argument("--profile", default="optimized")
    ap.add_argument("--roles", default="{}", help="JSON: core -> role label, from run_demo.py")
    a = ap.parse_args()
    state = State(a.profile, json.loads(a.roles))
    threading.Thread(target=udp_loop, args=(state, a.bus_port), daemon=True).start()
    threading.Thread(target=system_loop, args=(state,), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(state))
    srv.daemon_threads = True
    print(f"[hub] dashboard on http://0.0.0.0:{a.port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
