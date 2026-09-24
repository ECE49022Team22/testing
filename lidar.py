#!/usr/bin/env python3
"""
Minimal STL-27L LiDAR reader for a Raspberry Pi's native UART (no ROS, no USB adapter).

Wiring (Pi header):  LiDAR 5V  -> pin 2 (5V)
                     LiDAR GND -> pin 6 (GND)
                     LiDAR PWM -> GND  (required unless you do external speed control)
                     LiDAR TX  -> pin 10 (GPIO15 / RXD)
Requires: pip install pyserial
Usage:    python3 stl27l.py [/dev/serial0]
"""
import struct
import sys
import time

import serial

PKT_LEN = 47
HEADER, VERLEN = 0x54, 0x2C
PKT_FMT = "<BBHH" + "HB" * 12 + "HHB"   # header, verlen, speed, start, 12x(dist, intensity), end, ts, crc


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

    def __init__(self, port="/dev/serial0", baud=921600):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.buf = bytearray()
        self.crc_errors = 0
        self.speed_dps = 0

    def packets(self):
        while True:
            self.buf += self.ser.read(self.ser.in_waiting or 1)
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
                yield struct.unpack(PKT_FMT, pkt)

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
    lidar = STL27L(sys.argv[1] if len(sys.argv) > 1 else "/dev/serial0")
    t0, n = time.time(), 0
    for scan in lidar.scans():
        n += 1
        fwd = [d for a, d, _ in scan if a < 5 or a > 355]
        if time.time() - t0 >= 1.0:
            print(f"{n / (time.time() - t0):5.1f} Hz | {len(scan):4d} pts | "
                  f"speed {lidar.speed_dps / 360:4.1f} rev/s | crc errs {lidar.crc_errors} | "
                  f"fwd min {min(fwd) if fwd else '-'} mm")
            t0, n = time.time(), 0
