"""Scheduling knobs for the robot apps: real-time priority, timer slack, CPU affinity, memory locking.

    import rt_tune
    rt_tune.apply(rt_prio=80)          # SCHED_FIFO 80 for this process and threads it starts later

SCHED_FIFO and mlockall need either root or an rtprio/memlock limit for the user, e.g.
/etc/security/limits.d/90-robot-rt.conf (installed by bench/setup_root.sh):
    sdteam22  -  rtprio   90
    sdteam22  -  memlock  unlimited
The kernel keeps 5% of each second for normal tasks (sched_rt_runtime_us), so a runaway RT loop
can't lock the Pi up completely, but an RT thread that busy-waits will still starve its core.
"""
import ctypes
import os
import sys

PR_SET_TIMERSLACK = 29
MCL_CURRENT, MCL_FUTURE = 1, 2
_libc = ctypes.CDLL(None, use_errno=True)


def set_timer_slack(ns=1):
    """Timer slack lets the kernel delay a sleeping SCHED_OTHER thread's wakeup (default 50 us)
    to batch timers. 1 ns = wake on time. Per thread; threads created afterwards inherit it."""
    if _libc.prctl(PR_SET_TIMERSLACK, ctypes.c_ulong(ns), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_TIMERSLACK)")


def set_rt(prio):
    """SCHED_FIFO at `prio` (1-99) for the calling thread; threads created afterwards inherit it."""
    os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(prio))


def lock_memory():
    """Keep all current and future pages in RAM so a page fault can't stall a deadline."""
    if _libc.mlockall(MCL_CURRENT | MCL_FUTURE) != 0:
        raise OSError(ctypes.get_errno(), "mlockall")


def apply(rt_prio=None, cpus=None, timerslack_ns=1, mlock=False):
    """Apply what's asked; warn (don't fail) when a knob isn't permitted, so apps still run."""
    for name, fn, arg in (("timer slack", set_timer_slack, timerslack_ns),
                          ("cpu affinity", lambda c: os.sched_setaffinity(0, c), cpus),
                          ("SCHED_FIFO", set_rt, rt_prio),
                          ("mlockall", lambda _: lock_memory(), True if mlock else None)):
        if arg is None:
            continue
        try:
            fn(arg)
        except OSError as e:
            print(f"rt_tune: {name} not applied ({e.strerror or e}); see rt_tune.py for limits",
                  file=sys.stderr)


def from_env():
    """Apply knobs from RT_PRIO / RT_CPUS ("1,2") / RT_TIMERSLACK_NS / RT_MLOCK=1 (benchmark configs)."""
    env = os.environ
    cpus = env.get("RT_CPUS")
    apply(rt_prio=int(env["RT_PRIO"]) if env.get("RT_PRIO") else None,
          cpus={int(c) for c in cpus.split(",")} if cpus else None,
          timerslack_ns=int(env["RT_TIMERSLACK_NS"]) if env.get("RT_TIMERSLACK_NS") else None,
          mlock=env.get("RT_MLOCK") == "1")
