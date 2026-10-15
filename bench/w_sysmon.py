#!/usr/bin/env python3
"""System sampler: per-core CPU use, clock, SoC temperature, throttling, PMIC rails.

Metrics
  cpuN_util_pct   busy share of each core per sample window
  freq_mhz        ARM clock (all four Pi 5 cores share one clock)
  temp_c          SoC temperature
  throttled       vcgencmd get_throttled bitmask (0 = never throttled / undervolted)
  vdd_core_a, ext5v_v   PMIC readings (core current, 5 V input)
"""
import re
import subprocess
import time

from common import Recorder, base_args, now


def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                name, *vals = line.split()
                vals = list(map(int, vals))
                idle = vals[3] + vals[4]            # idle + iowait
                out[name] = (sum(vals), idle)
    return out


def read(path, cast=int):
    try:
        with open(path) as f:
            return cast(f.read().strip())
    except OSError:
        return None


def main():
    ap = base_args(__doc__)
    ap.add_argument("--interval", type=float, default=0.5)
    a = ap.parse_args()
    rec = Recorder("sysmon", a.out)
    rec.ready()
    prev = cpu_times()
    i = 0
    while not rec.stopping:
        time.sleep(a.interval)
        t = now()
        cur = cpu_times()
        for name, (tot, idle) in cur.items():
            dt, di = tot - prev[name][0], idle - prev[name][1]
            if dt > 0:
                rec.add(f"{name}_util_pct", 100.0 * (dt - di) / dt, t)
        prev = cur
        rec.add("freq_mhz", read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") / 1000, t)
        rec.add("temp_c", read("/sys/class/thermal/thermal_zone0/temp") / 1000, t)
        if i % 4 == 0:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout
            rec.add("throttled", int(out.strip().split("=")[1], 16), t)
            adc = subprocess.run(["vcgencmd", "pmic_read_adc"], capture_output=True, text=True).stdout
            m = re.search(r"VDD_CORE_A current\(\d+\)=([\d.]+)A", adc)
            if m:
                rec.add("vdd_core_a", float(m.group(1)), t)
            m = re.search(r"EXT5V_V volt\(\d+\)=([\d.]+)V", adc)
            if m:
                rec.add("ext5v_v", float(m.group(1)), t)
        i += 1
    rec.dump()


if __name__ == "__main__":
    main()
