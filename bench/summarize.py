#!/usr/bin/env python3
"""Turn a run directory into summary.json + summary.md (percentiles, rates, deadline misses).

  python3 summarize.py results/<run>
"""
import glob
import gzip
import json
import math
import os
import sys

# (worker, metric): (budget, why). A sample over budget counts as a deadline miss.
# These are starting points chosen from each device's timing, not hard requirements; tune them.
BUDGETS = {
    ("imu", "period_ms"): (15.0, "1.5x the 10 ms report period"),
    ("imu", "int_wait_ms"): (10.0, "BNO085 stops signalling if INT waits ~10 ms"),       # polling (old)
    ("imu", "int_latency_ms"): (10.0, "BNO085 stops signalling if INT waits ~10 ms"),    # edge events
    ("gps", "gga_jitter_ms"): (20.0, "GGA arrives >20 ms off the 5 Hz grid"),
    ("lidar", "excess_ms"): (10.0, "packet delivered >10 ms later than its best case"),
    ("lidar", "scan_period_ms"): (150.0, "1.5x the 100 ms scan period"),
    ("motor", "cmd_rtt_ms"): (20.0, "command -> ack over USB-UART"),
    ("motor", "telem_period_ms"): (150.0, "1.5x the 100 ms telemetry period"),
    ("yolo", "e2e_ms"): (500.0, "capture -> detection"),
    ("cell", "poll_rtt_ms"): (500.0, "one Notecard request over I2C"),
}

# Rate = count / duration for these (worker, counter, label).
RATES = [("imu", "samples", "IMU samples/s"), ("gps", "lines", "GPS NMEA lines/s"),
         ("lidar", "packets", "LiDAR packets/s"), ("yolo", "frames", "YOLO frames/s"),
         ("motor", "telemetry", "motor telemetry lines/s")]

HEADLINE = [("imu", "period_ms"), ("imu", "int_wait_ms"), ("imu", "int_latency_ms"), ("gps", "gga_jitter_ms"),
            ("lidar", "excess_ms"), ("lidar", "scan_period_ms"), ("yolo", "e2e_ms"),
            ("yolo", "infer_ms"), ("motor", "cmd_rtt_ms"), ("cell", "poll_rtt_ms")]


def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def stats(vals, budget=None):
    v = sorted(vals)
    if not v:
        return {"n": 0}
    mean = sum(v) / len(v)
    out = {"n": len(v), "mean": mean, "std": math.sqrt(sum((x - mean) ** 2 for x in v) / len(v)),
           "min": v[0], "p50": pct(v, 50), "p90": pct(v, 90), "p99": pct(v, 99),
           "p99.9": pct(v, 99.9), "max": v[-1]}
    if budget is not None:
        out["budget"] = budget
        out["over_budget"] = sum(1 for x in v if x > budget)
        out["over_budget_pct"] = 100 * out["over_budget"] / len(v)
    return out


LIDAR_TS_WRAP = 30000      # STL-27L packet timestamp: ms, wraps at 30000


def lidar_offsets(raw):
    """(host t, raw device ts) -> (host t, host ms - unwrapped device ms), dropping packets whose
    timestamp disagrees with the host clock by >200 ms. Those are corrupted packets that
    passed the 8-bit CRC by chance (~1 in 256 corrupted packets does)."""
    out, rejected, run = [], 0, 0
    last_t = last_dev = None
    for t, ts in raw:
        if last_t is None or run >= 50:             # (re)anchor
            last_t, last_dev, run = t, ts, 0
            out.append((t, t * 1e3 - ts))
            continue
        expected = last_dev + (t - last_t) * 1e3
        dev = ts + round((expected - ts) / LIDAR_TS_WRAP) * LIDAR_TS_WRAP
        if ts >= LIDAR_TS_WRAP or abs(dev - expected) > 200:
            rejected += 1
            run += 1
            continue
        run = 0
        last_t, last_dev = t, dev
        out.append((t, t * 1e3 - dev))
    return out, rejected


def lidar_excess(samples):
    """pkt_offset_ms -> excess delivery latency: subtract a line fitted to per-second minima
    (removes the fixed offset and the drift between the LiDAR's clock and the Pi's)."""
    if len(samples) < 20:
        return []
    buckets = {}
    for t, off in samples:
        k = int(t)
        buckets[k] = min(off, buckets.get(k, off))
    xs, ys = list(buckets), list(buckets.values())
    if len(xs) < 2:
        return []
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    a = my - b * mx
    resid = [(t, off - (a + b * t)) for t, off in samples]
    floor = min(r for _, r in resid)
    return [(t, r - floor) for t, r in resid]


def load_samples(path):
    """A worker's raw sample file: <name>.json, or <name>.json.gz once compress_raw() has run."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    with gzip.open(path + ".gz", "rt") as f:
        return json.load(f)


def compress_raw(run_dir):
    """gzip the raw per-worker sample files (~4x smaller) and drop the .ready markers.
    summary.json/md, meta.json, env.json and logs/ stay plain text."""
    for path in glob.glob(os.path.join(run_dir, "*.json")):
        if os.path.basename(path) in ("summary.json", "meta.json", "env.json"):
            continue
        with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:
            dst.write(src.read())
        os.remove(path)
    for path in glob.glob(os.path.join(run_dir, "*.ready")):
        os.remove(path)


def jitter_stats(path):
    d = load_samples(path)
    out = {}
    for cpu, c in d["cpus"].items():
        hist = sorted((int(k), n) for k, n in c["hist"].items())
        total = sum(n for _, n in hist)

        def q(p):
            target, acc = total * p / 100, 0
            for us, n in hist:
                acc += n
                if acc >= target:
                    return us
            return hist[-1][0] if hist else None

        out[f"cpu{cpu}"] = {"n": total, "mean": c["mean_us"], "p50": q(50), "p99": q(99),
                            "p99.9": q(99.9), "max": c["max_us"],
                            "over_100us_pct": 100 * sum(n for us, n in hist if us > 100) / max(total, 1),
                            "over_1ms_pct": 100 * sum(n for us, n in hist if us > 1000) / max(total, 1)}
    return out


def summarize(run_dir):
    with open(os.path.join(run_dir, "meta.json")) as f:
        meta = json.load(f)
    t0, t1 = meta["t_go"], meta["t_end"]
    dur = t1 - t0
    res = {"run": os.path.basename(os.path.normpath(run_dir)), "duration_s": dur,
           "workers": {}, "rates": {}, "proc": meta.get("proc", {}), "missing": []}

    for name in meta["workers"]:
        path = os.path.join(run_dir, f"{name}.json")
        if not (os.path.exists(path) or os.path.exists(path + ".gz")):
            res["missing"].append(name)
            continue
        if name == "jitter":
            res["jitter"] = jitter_stats(path)
            continue
        d = load_samples(path)
        samples = {m: [(t, v) for t, v in s if t0 <= t <= t1] for m, s in d["samples"].items()}
        if name == "lidar":
            if "pkt_offset_ms" in samples:       # older runs: recover the raw timestamp
                samples["pkt_ts_raw"] = [(t, (t * 1e3 - o) % LIDAR_TS_WRAP) for t, o in samples.pop("pkt_offset_ms")]
            if "pkt_ts_raw" in samples:
                offs, bad = lidar_offsets(samples.pop("pkt_ts_raw"))
                samples["excess_ms"] = lidar_excess(offs)
                d.setdefault("counters", {})["bad_timestamps_passed_crc"] = bad
        if name == "gps" and samples.get("gga_period_ms"):
            per = sorted(v for _, v in samples["gga_period_ms"])
            nominal = round(pct(per, 50) / 50) * 50 or pct(per, 50)   # 200 ms at 5 Hz
            samples["gga_jitter_ms"] = [(t, abs(v - nominal)) for t, v in samples["gga_period_ms"]]
        w = {"info": d.get("info", {}), "counters": d.get("counters", {}), "metrics": {}}
        for m, s in samples.items():
            budget = BUDGETS.get((name, m), (None,))[0]
            w["metrics"][m] = stats([v for _, v in s], budget)
        res["workers"][name] = w

    for name, counter, label in RATES:
        w = res["workers"].get(name)
        if w:
            # counters cover the whole process lifetime; use in-window sample counts where possible
            n = {"imu": "period_ms", "yolo": "loop_ms", "motor": "telem_period_ms",
                 "gps": "line_gap_ms"}.get(name)
            if n and n in w["metrics"]:
                res["rates"][label] = w["metrics"][n]["n"] / dur
            elif name == "lidar" and "excess_ms" in w["metrics"]:
                res["rates"][label] = w["metrics"]["excess_ms"]["n"] / dur
    scans = res["workers"].get("lidar", {}).get("metrics", {}).get("scan_period_ms", {}).get("n")
    if scans:
        res["rates"]["LiDAR scans/s"] = scans / dur

    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(res, f, indent=1)
    md = to_markdown(res)
    with open(os.path.join(run_dir, "summary.md"), "w") as f:
        f.write(md)
    return md


def fmt(x, nd=2):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def to_markdown(res):
    L = [f"# Benchmark {res['run']}", "", f"Measured window: {res['duration_s']:.0f} s", ""]
    if res["missing"]:
        L += [f"**No data from:** {', '.join(res['missing'])} (see logs/)", ""]
    L += ["## Latency (ms)", "",
          "| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, w in res["workers"].items():
        if name == "sysmon":
            continue
        for m, s in w["metrics"].items():
            if not s.get("n") or not m.endswith("_ms"):
                continue
            ob = f"{s['over_budget']} ({s['over_budget_pct']:.2f}%)" if "budget" in s else ""
            L.append(f"| {name} | {m} | {s['n']} | {fmt(s['p50'])} | {fmt(s['p90'])} | {fmt(s['p99'])} | "
                     f"{fmt(s['p99.9'])} | {fmt(s['max'])} | {fmt(s.get('budget'), 0)} | {ob} |")
    L += ["", "## Throughput", "", "| stream | rate |", "|---|---:|"]
    for k, v in res["rates"].items():
        if v:
            L.append(f"| {k} | {v:.2f} |")
    cnt = []
    for name, w in res["workers"].items():
        for k, v in w["counters"].items():
            if k in ("errors", "crc_errors", "timeouts", "overruns", "bad_lines", "read_failures",
                     "err_replies", "fault_lines", "bad_timestamps_passed_crc", "stalls", "rejected", "bad_headers", "pps_pulses", "gga_with_fix", "frames_with_stop_sign"):
                cnt.append(f"| {name} | {k} | {v} |")
    if cnt:
        L += ["", "## Event counters (whole process lifetime)", "", "| worker | counter | count |",
              "|---|---|---:|"] + cnt
    if "jitter" in res:
        L += ["", "## Scheduling latency, 1 kHz timer per core (µs)", "",
              "| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for c, s in res["jitter"].items():
            L.append(f"| {c} | {s['mean']:.1f} | {s['p50']} | {s['p99']} | {s['p99.9']} | {s['max']} | "
                     f"{s['over_100us_pct']:.2f}% | {s['over_1ms_pct']:.3f}% |")
    if res["proc"]:
        L += ["", "## Processes", "", "| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |",
              "|---|---:|---:|---:|---:|---|"]
        for n, p in res["proc"].items():
            L.append(f"| {n} | {p['cpu_pct']:.1f} | {p['invol_cs_per_s']:.1f} | {p['vol_cs_per_s']:.1f} | "
                     f"{p['threads']} | {','.join(map(str, p['cpus_seen']))} |")
    sm = res["workers"].get("sysmon", {}).get("metrics", {})
    if sm:
        L += ["", "## System", "", "| signal | mean | min | max |", "|---|---:|---:|---:|"]
        for m in sorted(sm):
            s = sm[m]
            if s.get("n"):
                if m == "throttled":
                    L.append(f"| throttled (bitmask) | | {hex(int(s['min']))} | {hex(int(s['max']))} |")
                else:
                    L.append(f"| {m} | {s['mean']:.2f} | {s['min']:.2f} | {s['max']:.2f} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    print(summarize(sys.argv[1]))
