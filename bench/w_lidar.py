#!/usr/bin/env python3
"""STL-27L LiDAR, same parser as testing/lidar.py, instrumented.

Metrics
  pkt_ts_raw      the LiDAR's own packet timestamp (ms, wraps at 30000), sampled at host arrival.
                  summarize.py turns it into excess_ms: delivery latency above the drift-corrected
                  best case = UART/DMA/kernel/scheduling delay.
  scan_period_ms  time between completed 360-degree scans (~100 ms at 10 Hz)
  scan_points     points per scan
"""
import sys

from common import TESTING, Recorder, base_args, log, now

sys.path.insert(0, TESTING)
import lidar as stl  # noqa: E402

class Stopped(Exception):
    """Raised from the serial read so a silent LiDAR can't block shutdown."""


class TimedSTL27L(stl.STL27L):
    """Same as STL27L, but remembers when each block of bytes arrived and can be told to stop."""

    def __init__(self, port, baud, rec, min_read):
        super().__init__(port, baud, min_read=min_read)
        self.rec = rec
        self.t_chunk = now()

    def _read(self):
        if self.rec.stopping:
            raise Stopped
        data = super()._read()
        self.t_chunk = now()
        return data

    def packets(self):
        for f in super().packets():
            self.rec.add("pkt_ts_raw", f[-2], self.t_chunk)   # summarize.py unwraps + validates it
            self.rec.count("packets")
            yield f


def main():
    ap = base_args(__doc__)
    ap.add_argument("--port", default="/dev/ttyAMA2")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--min-read", type=int, default=188, help="VMIN block size in bytes (1-255)")
    a = ap.parse_args()
    rec = Recorder("lidar", a.out)
    rec.info["min_read"] = a.min_read
    lid = TimedSTL27L(a.port, a.baud, rec, a.min_read)
    lid.ser.reset_input_buffer()
    rec.ready()
    last = None
    try:
        for scan in lid.scans():
            t = now()
            if last is not None:
                rec.add("scan_period_ms", (t - last) * 1e3, t)
                rec.add("scan_points", len(scan), t)
            last = t
            if rec.stopping:
                break
    except Stopped:
        pass
    finally:
        rec.counters["crc_errors"] = lid.crc_errors
        rec.counters["rejected"] = lid.rejected
        rec.dump()


if __name__ == "__main__":
    main()
