#!/usr/bin/env python3
"""Run every app at once (or one at a time with --solo) and benchmark latency.

  python3 run_bench.py                       # baseline.toml, everything concurrently
  python3 run_bench.py -c pinned.toml        # an experiment
  python3 run_bench.py --solo --duration 30  # each app alone, for an uncontended reference
  python3 run_bench.py --only imu motor      # a subset

Results land in results/<time>_<label>/ : one JSON per worker, logs/, env.json,
summary.md / summary.json. Compare runs with compare.py.
"""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import tomllib

from common import now
from summarize import compress_raw, summarize

HERE = os.path.dirname(os.path.abspath(__file__))
CLK_TCK = os.sysconf("SC_CLK_TCK")


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:
        return f"<{e}>"


def snapshot_env():
    cpu = "/sys/devices/system/cpu/cpu0/cpufreq/"
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "uname": sh("uname -a"),
        "model": sh("tr -d '\\0' < /proc/device-tree/model"),
        "governor": sh(f"cat {cpu}scaling_governor"),
        "freq_min_max_khz": sh(f"cat {cpu}scaling_min_freq {cpu}scaling_max_freq"),
        "throttled": sh("vcgencmd get_throttled"),
        "temp": sh("vcgencmd measure_temp"),
        "psu_max_current_ma": sh("od -An -tu4 --endian=big /proc/device-tree/chosen/power/max_current"),
        "cmdline": sh("cat /proc/cmdline"),
        "config_txt": sh("grep -vE '^\\s*(#|$)' /boot/firmware/config.txt"),
        "overlays": sh("dtoverlay -l"),
        "ftdi_latency_timer": sh("cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer"),
        "i2c_clock_hz": sh("od -An -tu4 --endian=big /sys/class/i2c-adapter/i2c-1/of_node/clock-frequency"),
        "preempt": sh("uname -v"),
        "top_cpu_before": sh("ps -eo pid,pcpu,comm --sort=-pcpu | head -12"),
    }


def proc_stats(pid):
    """Sum CPU time and context switches over all threads of a process."""
    cpu = vol = invol = 0
    cpus = set()
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            try:
                with open(f"/proc/{pid}/task/{tid}/stat") as f:
                    fields = f.read().rsplit(")", 1)[1].split()
                cpu += int(fields[11]) + int(fields[12])      # utime + stime
                cpus.add(int(fields[36]))                     # CPU last run on
                with open(f"/proc/{pid}/task/{tid}/status") as f:
                    for line in f:
                        if line.startswith("voluntary_ctxt_switches"):
                            vol += int(line.split()[1])
                        elif line.startswith("nonvoluntary_ctxt_switches"):
                            invol += int(line.split()[1])
            except OSError:
                pass
        threads = len(os.listdir(f"/proc/{pid}/task"))
    except OSError:
        return None
    return {"cpu_s": cpu / CLK_TCK, "vol_cs": vol, "invol_cs": invol, "threads": threads,
            "cpus_seen": sorted(cpus)}


def build_cmd(name, w, out):
    if "exec" in w:
        cmd = [os.path.join(HERE, w["exec"])]
    else:
        cmd = [os.path.expanduser(w["python"]), "-u", os.path.join(HERE, w["script"])]
    cmd += ["--out", out] + [str(x) for x in w.get("args", [])]
    if w.get("rt_prio"):
        cmd = ["chrt", "-f", str(w["rt_prio"])] + cmd
    if w.get("nice"):
        cmd = ["nice", "-n", str(w["nice"])] + cmd
    if w.get("cpus") is not None:
        cmd = ["taskset", "-c", str(w["cpus"])] + cmd
    return cmd


def start(name, w, run_dir):
    out = os.path.join(run_dir, f"{name}.json")
    cmd = build_cmd(name, w, out)
    env = dict(os.environ, **{k: str(v) for k, v in w.get("env", {}).items()})
    logf = open(os.path.join(run_dir, "logs", f"{name}.log"), "w")
    logf.write("$ " + shlex.join(cmd) + "\n")
    logf.flush()
    p = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=logf, stderr=subprocess.STDOUT,
                         start_new_session=True)
    return {"proc": p, "out": out, "cmd": cmd, "log": logf}


def wait_ready(procs, timeout):
    t0 = time.time()
    pending = set(procs)
    while pending and time.time() - t0 < timeout:
        for name in list(pending):
            p = procs[name]
            if os.path.exists(p["out"] + ".ready"):
                pending.discard(name)
            elif p["proc"].poll() is not None:
                print(f"  !! {name} exited during start-up (code {p['proc'].returncode}), see logs/{name}.log")
                pending.discard(name)
        time.sleep(0.2)
    for name in pending:
        print(f"  !! {name} not ready after {timeout}s, measuring anyway")


def stop_all(procs, probes=()):
    # Probes first, so the apps' shutdown (JSON dumps) isn't counted as scheduling latency.
    for name in sorted(procs, key=lambda n: n not in probes):
        p = procs[name]
        if p["proc"].poll() is None:
            p["proc"].send_signal(signal.SIGINT)
        if name in probes:
            try:
                p["proc"].wait(5)
            except subprocess.TimeoutExpired:
                pass
    deadline = time.time() + 15
    for name, p in procs.items():
        try:
            p["proc"].wait(max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            print(f"  !! {name} ignored SIGINT, killing (its samples are lost)")
            p["proc"].kill()
        p["log"].close()


def run(cfg, names, duration, run_dir):
    procs = {}
    try:
        return _run(cfg, names, duration, run_dir, procs)
    except BaseException:
        print("  !! interrupted, stopping workers")
        stop_all(procs)
        raise


def _run(cfg, names, duration, run_dir, procs):
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    workers = cfg["workers"]
    apps = [n for n in names if not workers[n].get("probe")]
    probes = [n for n in names if workers[n].get("probe")]

    print(f"starting apps: {', '.join(apps)}")
    procs.update({n: start(n, workers[n], run_dir) for n in apps})
    wait_ready(procs, cfg["run"].get("ready_timeout_s", 120))
    if probes:
        print(f"starting probes: {', '.join(probes)}")
        pp = {n: start(n, workers[n], run_dir) for n in probes}
        wait_ready(pp, 10)
        procs.update(pp)

    alive = {n: p for n, p in procs.items() if p["proc"].poll() is None}
    before = {n: proc_stats(p["proc"].pid) for n, p in alive.items()}
    t_go = now()
    print(f"measuring for {duration}s ...")
    while now() - t_go < duration:
        time.sleep(max(0.0, min(10.0, duration - (now() - t_go))))
        dead = [n for n, p in alive.items() if p["proc"].poll() is not None]
        for n in dead:
            print(f"  !! {n} died mid-run (code {alive[n]['proc'].returncode}), see logs/{n}.log")
            alive.pop(n)
        print(f"  {now() - t_go:5.0f}s / {duration}s")
    t_end = now()
    after = {n: proc_stats(p["proc"].pid) for n, p in alive.items()}
    stop_all(procs, probes)

    proc = {}
    for n in alive:
        b, a = before.get(n), after.get(n)
        if b and a:
            proc[n] = {"cpu_pct": 100 * (a["cpu_s"] - b["cpu_s"]) / (t_end - t_go),
                       "invol_cs_per_s": (a["invol_cs"] - b["invol_cs"]) / (t_end - t_go),
                       "vol_cs_per_s": (a["vol_cs"] - b["vol_cs"]) / (t_end - t_go),
                       "threads": a["threads"], "cpus_seen": a["cpus_seen"],
                       "cmd": shlex.join(procs[n]["cmd"])}
    meta = {"t_go": t_go, "t_end": t_end, "duration_s": t_end - t_go, "workers": names, "proc": proc}
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return meta


def hooks(cmds, when):
    """Per-worker pre/post shell commands, e.g. pausing a service that owns a bus we benchmark."""
    for c in cmds:
        print(f"{when}: {c}")
        subprocess.run(os.path.expanduser(c), shell=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "baseline.toml"))
    ap.add_argument("--duration", type=float, help="override run.duration_s")
    ap.add_argument("--label", help="override run.label")
    ap.add_argument("--only", nargs="+", help="run just these workers (probes are always added)")
    ap.add_argument("--solo", action="store_true", help="run each app alone, one after another")
    ap.add_argument("--no-probes", action="store_true")
    a = ap.parse_args()

    with open(a.config, "rb") as f:
        cfg = tomllib.load(f)
    duration = a.duration or cfg["run"]["duration_s"]
    label = a.label or cfg["run"].get("label", "run")
    workers = cfg["workers"]
    names = [n for n, w in workers.items() if w.get("enabled", True)]
    if a.only:
        names = [n for n in names if n in a.only or workers[n].get("probe")]
    if a.no_probes:
        names = [n for n in names if not workers[n].get("probe")]

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join(HERE, "results", f"{stamp}_{label}{'_solo' if a.solo else ''}")
    pre = [c for n in names for c in workers[n].get("pre", [])]
    post = [c for n in names for c in workers[n].get("post", [])]
    hooks(pre, "pre")
    try:
        env = snapshot_env()
        env["config"] = cfg
        if a.solo:
            probes = [n for n in names if workers[n].get("probe")]
            for n in [n for n in names if not workers[n].get("probe")]:
                print(f"=== solo: {n}")
                d = os.path.join(base, n)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "env.json"), "w") as f:
                    json.dump(env, f, indent=1)
                run(cfg, [n] + probes, duration, d)
                summarize(d)
                compress_raw(d)
                time.sleep(2)
            print(f"\nresults: {base}")
        else:
            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, "env.json"), "w") as f:
                json.dump(env, f, indent=1)
            run(cfg, names, duration, base)
            print(summarize(base))
            compress_raw(base)
            print(f"\nresults: {base}")
    finally:
        hooks(post, "post")


if __name__ == "__main__":
    sys.exit(main())
