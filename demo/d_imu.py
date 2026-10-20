#!/usr/bin/env python3
"""Demo worker: BNO085 IMU (SPI), same loop as testing/imu.py (INT edge events + watchdog).

Publishes orientation at ~25 Hz and, every 0.5 s, the timing that matters: sample rate, INT-edge ->
serviced latency (kernel timestamp), sample period, late samples (> 15 ms), watchdog resets.
"""
import math
import sys
import time

from bus import TESTING, Pub, Window, every, install_stop, now

sys.path.insert(0, TESTING)
from imu import (BNO_REPORT_ACCELEROMETER, BNO_REPORT_GYROSCOPE,  # noqa: E402
                 BNO_REPORT_ROTATION_VECTOR, Watchdog, close_imu, open_imu, quat_to_euler)

LATE_MS = 15.0


def main():
    stop = install_stop()
    pub = Pub("imu")
    lat, per = Window(0.5), Window(0.5)       # one window per published stats message
    st = {"samples": 0, "late": 0, "resets": 0, "bad_headers": 0, "t0": now(), "n0": 0}

    def stats():
        t = now()
        rate = (st["samples"] - st["n0"]) / max(1e-6, t - st["t0"])
        st["t0"], st["n0"] = t, st["samples"]
        pub.send("stats", rate_hz=round(rate, 1), int_latency_ms=lat.summary(), period_ms=per.summary(),
                 samples=st["samples"], late=st["late"], resets=st["resets"], bad_headers=st["bad_headers"])

    every(0.5, stats, stop)
    while not stop.is_set():
        pub.status("starting", "opening BNO085 on SPI0")
        try:
            bno = open_imu(interval_us=10_000)
        except Exception as e:
            pub.status("disconnected", f"{type(e).__name__}: {e}")
            stop.wait(5)
            continue
        pub.status("ok", "BNO085 on SPI0, 100 Hz, INT on GPIO25")
        irq, dog = bno._int, Watchdog(bno, 0.2)
        last_sample = last_pub = None
        last_done_ns = 0
        try:
            while not stop.is_set():
                if not irq.wait_low(min(dog.remaining() or 0.001, 0.1)):
                    if dog.check():
                        st["resets"] += 1
                        pub.status("ok", f"watchdog reset #{st['resets']} (chip went silent)")
                    continue
                t_found = now()
                edge = irq.last_edge_ns
                if edge is not None and edge > last_done_ns:
                    lat.add((t_found * 1e9 - edge) / 1e6, t_found)
                try:
                    bno._process_available_packets()
                except Exception:
                    pass
                t_done = now()
                last_done_ns = t_done * 1e9
                st["bad_headers"] = bno.bad_headers
                q = bno._readings.pop(BNO_REPORT_ROTATION_VECTOR, None)
                if q is None:
                    continue
                dog.fed()
                st["samples"] += 1
                if last_sample is not None:
                    p = (t_done - last_sample) * 1e3
                    per.add(p, t_done)
                    if p > LATE_MS:
                        st["late"] += 1
                last_sample = t_done
                if last_pub is None or t_done - last_pub >= 0.04:
                    last_pub = t_done
                    roll, pitch, yaw = quat_to_euler(*q)
                    ax, ay, az = bno._readings.get(BNO_REPORT_ACCELEROMETER, (0.0, 0.0, 0.0))
                    gx, gy, gz = bno._readings.get(BNO_REPORT_GYROSCOPE, (0.0, 0.0, 0.0))
                    pub.send("data", rpy=[round(roll, 2), round(pitch, 2), round(yaw, 2)],
                             accel=[round(ax, 2), round(ay, 2), round(az, 2)],
                             gyro=[round(gx, 3), round(gy, 3), round(gz, 3)],
                             g=round(math.sqrt(ax * ax + ay * ay + az * az), 2))
        except Exception as e:
            pub.status("error", f"{type(e).__name__}: {e}")
            time.sleep(2)
        finally:
            close_imu(bno)


if __name__ == "__main__":
    main()
