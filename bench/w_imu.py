#!/usr/bin/env python3
"""BNO085 over SPI, same loop as testing/imu.py (edge-triggered INT + watchdog), instrumented.

Metrics
  period_ms       time between successive rotation-vector samples (ideal = 1000/hz)
  int_latency_ms  INT falling edge (kernel timestamp) -> this process starts the SPI read.
                  Over ~10 ms the BNO085 stops signalling.
  service_ms      SPI transfer + parse time for one INT (_process_available_packets)
  stalls          times no sample came for --watchdog s; each triggers a chip reset (counter)
"""
import sys

from common import TESTING, Recorder, base_args, log, now

sys.path.insert(0, TESTING)
from imu import BNO_REPORT_ROTATION_VECTOR, Watchdog, close_imu, open_imu  # noqa: E402


def main():
    ap = base_args(__doc__)
    ap.add_argument("--hz", type=float, default=100)
    ap.add_argument("--watchdog", type=float, default=0.2)
    a = ap.parse_args()
    rec = Recorder("imu", a.out)
    rec.info["hz"] = a.hz

    bno = open_imu(interval_us=int(1e6 / a.hz))
    irq = bno._int
    dog = Watchdog(bno, a.watchdog)
    rec.ready()
    last_sample = None
    last_done_ns = 0
    try:
        while not rec.stopping:
            if not irq.wait_low(min(dog.remaining() or 0.001, 0.1)):
                if not rec.stopping and dog.check():
                    rec.count("stalls")
                    rec.add("stall_at_s", now())
                    log("imu", f"no data for {a.watchdog} s: BNO085 reset")
                continue
            t_found = now()
            edge = irq.last_edge_ns
            if edge is not None and edge > last_done_ns:   # a fresh edge, not INT still low
                rec.add("int_latency_ms", (t_found * 1e9 - edge) / 1e6, t_found)
            try:
                bno._process_available_packets()
            except Exception as e:          # a dropped packet shouldn't end the run
                rec.count("errors")
                log("imu", f"error: {e!r}")
            t_done = now()
            last_done_ns = t_done * 1e9
            rec.add("service_ms", (t_done - t_found) * 1e3, t_done)
            if bno._readings.pop(BNO_REPORT_ROTATION_VECTOR, None) is None:
                continue
            dog.fed()
            if last_sample is not None:
                rec.add("period_ms", (t_done - last_sample) * 1e3, t_done)
            last_sample = t_done
            rec.count("samples")
    finally:
        rec.counters["bad_headers"] = bno.bad_headers
        rec.dump()
        close_imu(bno)


if __name__ == "__main__":
    main()
