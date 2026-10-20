#!/usr/bin/env python3
"""Demo worker: STL-27L LiDAR on UART2 (/dev/ttyAMA2, RX pin 29), parser from testing/lidar.py.

Publishes each 360-degree scan as 1-degree bins (nearest return per degree, mm) and, every 0.5 s,
scan rate, delivery latency above best case (host arrival vs the LiDAR's own packet timestamp,
relative to the lowest offset seen in the last few seconds), CRC errors and rejected packets.
"""
import collections
import sys

from bus import TESTING, Pub, Window, every, install_stop, now

sys.path.insert(0, TESTING)
import lidar as stl  # noqa: E402

PORT, BAUD, TS_WRAP = "/dev/ttyAMA2", 921600, 30000


class Stopped(Exception):
    pass


class DemoLidar(stl.STL27L):
    def __init__(self, stop, st):
        super().__init__(PORT, BAUD)
        self.stop, self.st, self.t_chunk = stop, st, now()

    def _read(self):
        if self.stop.is_set():
            raise Stopped
        data = super()._read()
        self.t_chunk = now()
        self.st["bytes"] += len(data)
        return data

    def packets(self):
        for f in super().packets():
            self.st["packets"] += 1
            self.st["last_packet"] = now()
            off = (self.t_chunk * 1e3 - f[-2]) % TS_WRAP     # host ms minus device ms (mod the wrap)
            self.st["offsets"].append((self.t_chunk, off))
            self.st["new"].append((self.t_chunk, off))
            yield f


def main():
    stop = install_stop()
    pub = Pub("lidar")
    excess = Window()
    st = {"bytes": 0, "packets": 0, "scans": 0, "last_packet": 0.0, "offsets": collections.deque(), "new": collections.deque(),
          "t0": now(), "s0": 0, "b0": 0, "p0": 0, "lid": None}

    def stats():
        t = now()
        dt = max(1e-6, t - st["t0"])
        rates = dict(scan_hz=round((st["scans"] - st["s0"]) / dt, 2), packets_s=round((st["packets"] - st["p0"]) / dt),
                     bytes_s=round((st["bytes"] - st["b0"]) / dt))
        st["t0"], st["s0"], st["b0"], st["p0"] = t, st["scans"], st["bytes"], st["packets"]
        # delivery latency above best case: offset minus the minimum offset of the last 5 s
        offs = st["offsets"]
        while offs and offs[0][0] < t - 5:
            offs.popleft()
        new = st["new"]
        if offs:
            base = min(o for _, o in offs)
            while new:
                tt, o = new.popleft()
                excess.add((o - base + TS_WRAP / 2) % TS_WRAP - TS_WRAP / 2, tt)
        lid = st["lid"]
        pub.send("stats", **rates, excess_ms=excess.summary(), scans=st["scans"],
                 crc_errors=lid.crc_errors if lid else 0, rejected=lid.rejected if lid else 0,
                 speed_rps=round(lid.speed_dps / 360, 1) if lid else 0)
        if lid and t - st["last_packet"] > 2:
            if rates["bytes_s"] > 1000:
                pub.status("nodata", f"{rates['bytes_s']} bytes/s arriving but no valid packets: "
                                     f"check the LiDAR TX wire on pin 29 and its baud ({BAUD})")
            else:
                pub.status("nodata", "no bytes on pin 29: LiDAR unpowered or TX not connected")
        elif lid:
            pub.status("ok", f"STL-27L on {PORT} @ {BAUD}")

    every(0.5, stats, stop)
    while not stop.is_set():
        try:
            st["lid"] = lid = DemoLidar(stop, st)
        except Exception as e:
            pub.status("disconnected", f"{PORT}: {e}")
            stop.wait(5)
            continue
        pub.status("starting", f"reading {PORT}")
        try:
            for scan in lid.scans():
                st["scans"] += 1
                bins = [0] * 360
                for a, d, _ in scan:
                    i = int(a) % 360
                    if bins[i] == 0 or d < bins[i]:
                        bins[i] = d
                fwd = [d for a, d, _ in scan if a < 10 or a > 350]
                pub.send("scan", bins=bins, points=len(scan), fwd_min_mm=min(fwd) if fwd else None)
        except Stopped:
            break
        except Exception as e:
            pub.status("error", f"{type(e).__name__}: {e}")
            stop.wait(2)
        finally:
            try:
                lid.ser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
