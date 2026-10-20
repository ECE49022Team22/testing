"""Plumbing shared by the demo workers: publish to the hub, rolling latency stats.

Workers are separate processes (like the real apps) pinned and prioritised by run_demo.py. They
publish small JSON datagrams to the hub over localhost UDP: sendto() never blocks, so a slow or
absent dashboard can't delay a real-time sensor loop. Messages that don't arrive are just dropped.
"""
import collections
import json
import os
import socket
import sys
import threading
import time

HOME = os.path.expanduser("~")
TESTING = os.path.join(HOME, "testing")
YOLO_DIR = os.path.join(HOME, "stop-sign-eval")
HUB_ADDR = ("127.0.0.1", int(os.environ.get("DEMO_BUS_PORT", "8765")))

# run_demo.py passes RT_TIMERSLACK_NS / RT_MLOCK (and chrt/taskset for priority and cores).
sys.path.append(TESTING)
import rt_tune  # noqa: E402
rt_tune.from_env()


def now():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


class Pub:
    def __init__(self, name):
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def send(self, kind, **data):
        msg = {"src": self.name, "kind": kind, "pid": os.getpid(), "t": time.time(), **data}
        try:
            self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), HUB_ADDR)
        except (BlockingIOError, OSError):
            pass                                     # hub busy or not running: drop it

    def status(self, state, detail=""):
        """state: 'ok' | 'starting' | 'nodata' | 'disconnected' | 'error'"""
        self.send("status", state=state, detail=detail)


class Window:
    """Samples from the last `span` seconds; summary() gives the numbers the tiles show."""

    def __init__(self, span=5.0):
        self.span = span
        self.d = collections.deque()
        self.lock = threading.Lock()
        self.total = 0

    def add(self, v, t=None):
        t = now() if t is None else t
        with self.lock:
            self.d.append((t, v))
            self.total += 1
            while self.d and self.d[0][0] < t - self.span:
                self.d.popleft()

    def summary(self):
        with self.lock:
            cutoff = now() - self.span
            while self.d and self.d[0][0] < cutoff:
                self.d.popleft()
            v = sorted(x for _, x in self.d)
        if not v:
            return None
        pick = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
        return {"p50": round(pick(0.50), 3), "p99": round(pick(0.99), 3), "max": round(v[-1], 3), "n": len(v)}


def every(period, fn, stop):
    """Call fn() every `period` seconds on a daemon thread until stop.is_set()."""
    def loop():
        nxt = now()
        while not stop.is_set():
            nxt += period
            try:
                fn()
            except Exception as e:                    # a stats bug must not kill the sensor loop
                print(f"stats error: {e!r}", file=sys.stderr, flush=True)
            stop.wait(max(0.0, nxt - now()))
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return th


def install_stop():
    """SIGINT/SIGTERM set the returned Event (workers poll it)."""
    import signal
    ev = threading.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: ev.set())
    return ev
