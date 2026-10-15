#!/usr/bin/env python3
"""Compare testing/lidar.py with the original parser (git 1ea4929) on synthetic STL-27L streams.

    cd ~/testing && .venv/bin/python bench/tools/test_lidar_parser.py

Checks: identical packets and scans on a clean stream; no bogus packets from a stream with dropped /
flipped bytes; CRC-valid but corrupt packets (bad timestamp or angle) rejected by the new parser only.
Used for the parser claims in ROUND1_RESULTS.md.
"""
import os
import random
import struct
import subprocess
import sys
import tempfile

TESTING = os.path.expanduser("~/testing")
sys.path.insert(0, TESTING)
import lidar as new  # noqa: E402

tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "lidar_old.py"), "w") as f:
    f.write(subprocess.run(["git", "-C", TESTING, "show", "1ea4929:lidar.py"],
                           capture_output=True, text=True, check=True).stdout)
sys.path.insert(0, tmp)
import lidar_old as old  # noqa: E402

PKT = 47


def stream(seconds, corrupt=0.0, seed=1):
    rnd = random.Random(seed)
    out, clean, ang, ts = bytearray(), [], 0.0, 25000
    for i in range(int(1750 * seconds)):
        start = int(ang) % 36000
        ang += 205.7
        end = int(ang) % 36000
        ts = (ts + (1 if i % 4 else 0)) % 30000
        pts = sum([[rnd.randint(0, 12000) * (rnd.random() > .1), rnd.randint(0, 255)] for _ in range(12)], [])
        body = struct.pack("<BBHH" + "HB" * 12 + "HH", 0x54, 0x2C, 3600, start, *pts, end, ts)
        pkt = body + bytes([old.crc8(body)])
        clean.append(struct.unpack(old.PKT_FMT, pkt))
        b = bytearray(pkt)
        if corrupt and rnd.random() < corrupt:          # drop or flip one byte
            j = rnd.randrange(len(b))
            if rnd.random() < .5:
                del b[j]
            else:
                b[j] ^= 1 << rnd.randrange(8)
        out += b
    return bytes(out), clean


class Feed:
    def __init__(self, data, chunk):
        self.data, self.i, self.chunk = data, 0, chunk

    def read(self, _n=None):
        if self.i >= len(self.data):
            raise EOFError
        d = self.data[self.i:self.i + self.chunk]
        self.i += self.chunk
        return d


def old_reader(data):
    r = old.STL27L.__new__(old.STL27L)
    r.buf, r.crc_errors, r.speed_dps = bytearray(), 0, 0
    feed = Feed(data, 13)
    r.ser = type("S", (), {"read": lambda s, n: feed.read(), "in_waiting": 0})()
    return r


def new_reader(data):
    r = new.STL27L.__new__(new.STL27L)
    r.buf, r.crc_errors, r.rejected, r.speed_dps = bytearray(), 0, 0, 0
    r._last_ts, r._suspect_run = None, 0
    r._read = Feed(data, 188).read
    return r


def drain(gen):
    out = []
    try:
        for x in gen:
            out.append(x)
    except (EOFError, RuntimeError):
        pass
    return out


ok = True
data, clean = stream(5)
po, pn = drain(old_reader(data).packets()), drain(new_reader(data).packets())
so, sn = drain(old_reader(data).scans()), drain(new_reader(data).scans())
same_scans = len(so) == len(sn) and all(
    len(a) == len(b) and all(abs(x[0] - y[0]) < 1e-9 and x[1:] == y[1:] for x, y in zip(a, b)) for a, b in zip(so, sn))
print(f"clean stream:   packets identical {po == pn} ({len(pn)}), scans identical {same_scans} ({len(sn)})")
ok &= po == pn and same_scans

data, clean = stream(10, corrupt=0.02)
cs = set(clean)
po, rn = drain(old_reader(data).packets()), new_reader(data)
pn = drain(rn.packets())
bo, bn = sum(p not in cs for p in po), sum(p not in cs for p in pn)
print(f"damaged stream: old {len(po)} packets ({bo} bogus), new {len(pn)} packets ({bn} bogus), crc errors {rn.crc_errors}")
ok &= bn == 0 and len(pn) == len(po)

data, clean = stream(5)
raw = bytearray(data)
for k in range(50):                                    # CRC-valid but impossible packets
    i = (k * 173 + 11) * PKT
    f = list(struct.unpack(old.PKT_FMT, raw[i:i + PKT]))
    if k % 2:
        f[-2] = (f[-2] + 12345) % 30000                # timestamp jumps
    else:
        f[3] = 40000                                   # start angle > 360 deg
    body = struct.pack(old.PKT_FMT[:-1], *f[:-1])
    raw[i:i + PKT] = body + bytes([old.crc8(body)])
cs = set(clean)
po, rn = drain(old_reader(bytes(raw)).packets()), new_reader(bytes(raw))
pn = drain(rn.packets())
print(f"50 CRC-valid bad packets: old passed {sum(p not in cs for p in po)}, new passed {sum(p not in cs for p in pn)} "
      f"(rejected {rn.rejected}); good packets kept old {sum(p in cs for p in po)} new {sum(p in cs for p in pn)}")
ok &= sum(p not in cs for p in pn) == 0 and sum(p in cs for p in pn) == sum(p in cs for p in po)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
