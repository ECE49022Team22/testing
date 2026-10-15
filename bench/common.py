"""Shared plumbing for the benchmark workers.

Every worker is its own process (like the real apps), records (t, value) samples per metric
with CLOCK_MONOTONIC timestamps in seconds, and dumps them as JSON when it is stopped.
The runner only counts samples taken after it says "go", so start-up cost is excluded.
"""
import argparse
import json
import os
import signal
import sys
import time

HOME = os.path.expanduser("~")
TESTING = os.path.join(HOME, "testing")
CELL_DIR = os.path.join(TESTING, "cellular_test")
YOLO_DIR = os.path.join(HOME, "stop-sign-eval")

# RT_PRIO / RT_CPUS / RT_TIMERSLACK_NS / RT_MLOCK from the config's env apply to every worker.
sys.path.append(TESTING)
import rt_tune  # noqa: E402
rt_tune.from_env()


def now():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


class Recorder:
    def __init__(self, name, out_path):
        self.name = name
        self.out_path = out_path
        self.samples = {}
        self.counters = {}
        self.info = {"pid": os.getpid()}
        self.stopping = False
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

    def _stop(self, *_):
        self.stopping = True

    def add(self, metric, value, t=None):
        self.samples.setdefault(metric, []).append((now() if t is None else t, value))

    def count(self, counter, n=1):
        self.counters[counter] = self.counters.get(counter, 0) + n

    def ready(self):
        """Tell the runner initialisation is done (it waits for every worker before 'go')."""
        open(self.out_path + ".ready", "w").close()
        log(self.name, "ready")

    def dump(self):
        try:                       # don't serialise samples at RT priority: it starves the core
            os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
        except OSError:
            pass
        self.info["affinity"] = sorted(os.sched_getaffinity(0))
        self.info["nice"] = os.nice(0)
        self.info["policy"] = os.sched_getscheduler(0)
        with open(self.out_path, "w") as f:
            json.dump({"name": self.name, "info": self.info, "counters": self.counters,
                       "samples": self.samples}, f)
        log(self.name, f"wrote {sum(map(len, self.samples.values()))} samples")


def log(name, msg):
    print(f"[{name}] {msg}", file=sys.stderr, flush=True)


def base_args(desc):
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--out", required=True, help="JSON file to write samples to")
    return ap
