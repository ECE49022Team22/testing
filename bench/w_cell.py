#!/usr/bin/env python3
"""Blues Notecard over I2C (pins 3/5), polling like cellular_test/receive_demo.py, instrumented.

Each poll is a non-destructive note.changes on commands.qi (receive_demo uses delete:true,
which would eat real commands); every 15th poll also does hub.status, like its watchdog.

Metrics
  poll_rtt_ms     note.changes request -> response over I2C
  status_rtt_ms   hub.status request -> response
  poll_late_ms    how late each poll started vs its 1 s schedule
"""
import sys
import time

from common import CELL_DIR, Recorder, base_args, log, now

sys.path.insert(0, CELL_DIR)
from notecard_link import NotecardLink, open_card  # noqa: E402


def main():
    ap = base_args(__doc__)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    rec = Recorder("cell", a.out)

    link = NotecardLink(open_card())
    rec.info["version"] = link.version().get("version")
    rec.ready()
    nxt = now()
    i = 0
    try:
        while not rec.stopping:
            t0 = now()
            rec.add("poll_late_ms", (t0 - nxt) * 1e3, t0)
            for metric, req in [("poll_rtt_ms", {"req": "note.changes", "file": "commands.qi"})] + (
                    [("status_rtt_ms", {"req": "hub.status"})] if i % 15 == 0 else []):
                t = now()
                try:
                    link.card.Transaction(req)
                    rec.add(metric, (now() - t) * 1e3)
                except Exception as e:
                    rec.count("errors")
                    log("cell", f"{req['req']}: {e!r}")
            i += 1
            nxt += a.interval
            while not rec.stopping and now() < nxt:
                time.sleep(min(0.1, max(0.0, nxt - now())))
    finally:
        rec.dump()


if __name__ == "__main__":
    main()
