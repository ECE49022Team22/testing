#!/usr/bin/env python3
"""
Minimal STL-27L LiDAR reader for a Raspberry Pi's native UART (no ROS, no USB adapter).

Wiring (Pi header):  LiDAR 5V  -> pin 2 (5V)
                     LiDAR GND -> pin 6 (GND)
                     LiDAR PWM -> GND  (required unless you do external speed control)
                     LiDAR TX  -> pin 29 (GPIO5 / UART2 RXD)
Requires: dtoverlay=uart2-pi5 in /boot/firmware/config.txt (-> /dev/ttyAMA2; it also claims
          GPIO4 / pin 7 as TXD2, which the LiDAR doesn't use)
          pip install pyserial
Usage:    python3 lidar.py [/dev/ttyAMA2]

The port is read in blocks (termios VMIN, default 188 bytes = 4 packets, ~2 ms at 921600 baud),
so the process wakes a few hundred times a second instead of once per few bytes (~6000/s before,
most of its CPU). Packets that pass the CRC but can't be right (timestamp, angles or speed out of
range, or timestamp out of sequence) are dropped: the 8-bit CRC lets ~1 in 256 corrupted packets
through.
"""
import fcntl
import os
import select
import struct
import sys
import termios
import time

import serial

PKT_LEN = 47
HEADER, VERLEN = 0x54, 0x2C
PKT_FMT = "<BBHH" + "HB" * 12 + "HHB"   # header, verlen, speed, start, 12x(dist, intensity), end, ts, crc

TS_WRAP = 30000            # packet timestamp: ms, wraps at 30000
MAX_TS_GAP_MS = 1000       # a packet more than this after the last good one is suspect
MAX_SPAN_CDEG = 1500       # one packet covers ~2 deg at 10 Hz; more than 15 deg is corrupt
SPEED_RANGE = (360, 14400) # deg/s (1-40 rev/s); nominal 3600


def _make_crc_table(poly=0x4D):
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        table.append(c)
    return table


CRC_TABLE = _make_crc_table()


def crc8(data):
    c = 0
    for b in data:
        c = CRC_TABLE[(c ^ b) & 0xFF]
    return c


class STL27L:
    """Reads packets and yields complete 360-degree scans as lists of (angle_deg, dist_mm, intensity)."""

    def __init__(self, port="/dev/ttyAMA2", baud=921600, min_read=188):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.fd = self.ser.fileno()
        # Blocking reads that return once min_read bytes (max 255) are in, or 0.1 s after the last byte.
        fcntl.fcntl(self.fd, fcntl.F_SETFL, fcntl.fcntl(self.fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[6][termios.VMIN] = max(1, min(255, min_read))
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        self.buf = bytearray()
        self.crc_errors = 0
        self.rejected = 0          # passed the CRC, failed plausible()
        self.speed_dps = 0
        self._last_ts = None
        self._suspect_run = 0

    def _read(self):
        """Next block of bytes (b"" if the LiDAR has been silent for 0.2 s)."""
        if not select.select([self.fd], [], [], 0.2)[0]:
            return b""
        return os.read(self.fd, 4096)

    def plausible(self, f):
        """False for a packet whose fields can't be right, or that is out of sequence."""
        speed, start, end, ts = f[2], f[3], f[-3], f[-2]
        if (ts >= TS_WRAP or start >= 36000 or end >= 36000 or (end - start) % 36000 > MAX_SPAN_CDEG
                or not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]):
            return False
        if self._last_ts is not None and (ts - self._last_ts) % TS_WRAP > MAX_TS_GAP_MS:
            self._suspect_run += 1
            if self._suspect_run < 3:      # 3 in a row agree with each other: re-anchor on them
                return False
        self._suspect_run = 0
        self._last_ts = ts
        return True

    def packets(self):
        while True:
            self.buf += self._read()
            while len(self.buf) >= PKT_LEN:
                i = self.buf.find(bytes((HEADER, VERLEN)))
                if i < 0:                       # no header: keep last byte in case it's a split 0x54
                    del self.buf[:-1]
                    break
                if i > 0:
                    del self.buf[:i]
                    continue
                pkt = bytes(self.buf[:PKT_LEN])
                if crc8(pkt[:-1]) != pkt[-1]:
                    self.crc_errors += 1
                    del self.buf[:1]           # resync on next header
                    continue
                del self.buf[:PKT_LEN]
                f = struct.unpack(PKT_FMT, pkt)
                if not self.plausible(f):
                    self.rejected += 1
                    continue
                yield f

    def scans(self):
        scan, last_angle = [], None
        for f in self.packets():
            self.speed_dps = f[2]
            start, end = f[3], f[-3]
            if end < start:                     # angle wrapped past 360 inside this packet
                end += 36000
            step = (end - start) / 11
            for k in range(12):
                dist, inten = f[4 + 2 * k], f[5 + 2 * k]
                angle = ((start + step * k) % 36000) / 100.0
                if last_angle is not None and angle < last_angle - 180:   # new revolution
                    yield scan
                    scan = []
                last_angle = angle
                if dist > 0:                    # 0 = no return
                    scan.append((angle, dist, inten))


if __name__ == "__main__":
    lidar = STL27L(sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyAMA2")
    t0, n = time.time(), 0
    for scan in lidar.scans():
        n += 1
        fwd = [d for a, d, _ in scan if a < 5 or a > 355]
        if time.time() - t0 >= 1.0:
            print(f"{n / (time.time() - t0):5.1f} Hz | {len(scan):4d} pts | "
                  f"speed {lidar.speed_dps / 360:4.1f} rev/s | crc errs {lidar.crc_errors} | "
                  f"rejected {lidar.rejected} | fwd min {min(fwd) if fwd else '-'} mm", flush=True)
            t0, n = time.time(), 0
