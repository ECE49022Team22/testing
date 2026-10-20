#!/usr/bin/env python3
"""Demo worker: Blues Notecard (cellular), read-only, from the running receiver's log.

The Notecard's I2C bus belongs to receive_demo.py (tmux session "cellular", started by cron), and two
processes can't share the card, so this never opens the bus. It follows
cellular_test/logs/cellular_log.txt and publishes the receiver's heartbeats (hub session, signal),
the other events it logs (commands received, session recovery), and whether the receiver is running.
"""
import os
import re
import subprocess

from bus import TESTING, Pub, every, install_stop

LOG = os.path.join(TESTING, "cellular_test", "logs", "cellular_log.txt")
HEARTBEAT = re.compile(r"^(\S+ \S+)\s+heartbeat: hub='([^']*)' bars=(\S+) rssi=(\S+) rsrp=(\S+) sinr=(\S+) rat=(\S+)")


def receiver_running():
    return subprocess.run(["tmux", "has-session", "-t", "cellular"], capture_output=True).returncode == 0


def main():
    stop = install_stop()
    pub = Pub("cell")
    st = {"pos": 0, "hb": None, "events": [], "inode": None}

    def num(v):
        try:
            return int(v)
        except ValueError:
            return None

    def poll():
        try:
            sb = os.stat(LOG)
        except FileNotFoundError:
            pub.status("disconnected", f"no receiver log at {LOG}")
            return
        if sb.st_ino != st["inode"] or sb.st_size < st["pos"]:      # rotated or new: start near the end
            st["inode"], st["pos"] = sb.st_ino, max(0, sb.st_size - 8000)
        with open(LOG, errors="replace") as f:
            f.seek(st["pos"])
            chunk = f.read()
            st["pos"] = f.tell()
        for line in chunk.splitlines():
            m = HEARTBEAT.match(line)
            if m:
                ts, hub, bars, rssi, rsrp, sinr, rat = m.groups()
                st["hb"] = dict(time=ts, hub=hub, bars=num(bars), rssi=num(rssi), rsrp=num(rsrp), sinr=num(sinr), rat=rat,
                                session_open="session open" in hub)
            elif line.strip():
                ts, _, msg = line.partition("  ")
                st["events"] = (st["events"] + [{"time": ts.strip(), "msg": msg.strip()[:160]}])[-6:]
        running = receiver_running()
        pub.send("data", heartbeat=st["hb"], events=st["events"], receiver=running)
        if not running:
            pub.status("nodata", "receive_demo.py is not running (cellular_test/cellular_logger.sh start)")
        elif st["hb"]:
            pub.status("ok", "read-only: following receive_demo.py's log (it owns the I2C bus)")
        else:
            pub.status("starting", "waiting for a heartbeat (once a minute)")

    every(2.0, poll, stop)
    stop.wait()


if __name__ == "__main__":
    main()
