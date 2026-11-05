#!/usr/bin/env python3
"""RTK for the UM982: NTRIP client that feeds RTCM corrections into the receiver over UART0.

    .venv/bin/python ntrip_rtk.py [--seconds 0] [--port /dev/ttyAMA0] [--baud 230400] [--rtcm-port /dev/ttyAMA4]

Connects to the NTRIP caster in ~/.config/ntrip.json ({"host", "port", "mountpoint", "user",
"password", "gga_interval_s"}; kept out of git), streams its RTCM 3 to the receiver (the Pi's TXD0,
pin 8, goes to the UM982's RX; the UM982 auto-detects RTCM on its COM ports), and sends the
receiver's own GGA back to the caster every gga_interval_s (a *_NEAR / VRS mountpoint needs it to
pick the base). Prints the fix type (1 GPS, 2 DGPS, 5 RTK float, 4 RTK fixed), correction age, base
station id, satellites and the RTCM message types arriving. Reconnects if the caster drops.

--rtcm-port sends the corrections out of a different UART than the one NMEA is read from (same baud).
On this Pi, UART0's TX (GPIO14, pin 8) doesn't drive its pin (found 2026-11-05: the UART sends at
full rate but the pin never leaves 3.3 V, while the pin itself works as a plain GPIO), so RTCM goes
out on UART4 TX instead: dtoverlay=uart4-pi5 -> /dev/ttyAMA4, GPIO12 = header pin 32 -> UM982 RX.

The serial port can only be read by one program: stop the demo's GPS worker first.
"""
import argparse
import base64
import collections
import json
import os
import socket
import threading
import time

import serial

FIX = {"0": "no fix", "1": "GPS", "2": "DGPS", "4": "RTK FIXED", "5": "RTK float", "6": "dead reckoning"}


class Receiver:
    """Reads NMEA from the UM982 and keeps the latest GGA; write() sends bytes (RTCM) to it."""

    def __init__(self, port, baud, rtcm_port=None, rtcm_baud=None):
        self.ser = serial.Serial(port, baud, timeout=0.5)
        self.out = serial.Serial(rtcm_port, rtcm_baud or baud, timeout=0.5) if rtcm_port else self.ser
        self.gga, self.gga_t = None, 0.0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while not self.stop.is_set():
            try:
                line = self.ser.readline()
            except serial.SerialException:
                time.sleep(0.5)
                continue
            if line[3:6] == b"GGA" and line.startswith(b"$"):
                self.gga, self.gga_t = line.strip(), time.monotonic()

    def write(self, data):
        with self.lock:
            self.out.write(data)


def rtcm_frames(buf, counts):
    """Count complete RTCM 3 frames (0xD3, 10-bit length, payload, CRC-24Q) by message type; returns leftover."""
    i = 0
    while True:
        j = buf.find(b"\xd3", i)
        if j < 0 or len(buf) - j < 6:
            return buf[j:] if j >= 0 else b""
        n = ((buf[j + 1] & 0x03) << 8) | buf[j + 2]
        if len(buf) - j < n + 6:
            return buf[j:]
        if n >= 2:
            counts[(buf[j + 3] << 4) | (buf[j + 4] >> 4)] += 1
        i = j + n + 6


def ntrip(cfg, rx, st, stop):
    auth = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
    req = (f"GET /{cfg['mountpoint']} HTTP/1.0\r\nUser-Agent: NTRIP sdteam22-robot/1.0\r\n"
           f"Authorization: Basic {auth}\r\nAccept: */*\r\nConnection: close\r\n\r\n").encode()
    while not stop.is_set():
        try:
            while rx.gga is None or rx.gga.split(b",")[6:7] in ([b"0"], [b""], []):
                st["state"] = "waiting for a GPS fix to send the caster"   # a NEAR mountpoint needs a position
                if stop.wait(1):
                    return
            s = socket.create_connection((cfg["host"], cfg["port"]), timeout=10)
            s.sendall(req)
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 4096:
                c = s.recv(1)
                if not c:
                    break
                head += c
                if head.startswith(b"ICY 200 OK\r\n"):     # NTRIP v1 casters answer "ICY 200 OK" with no headers
                    break
            first = head.split(b"\r\n")[0].decode(errors="replace")
            if not (first.startswith("ICY 200") or " 200 " in first):
                st["state"] = f"caster refused: {first}"
                s.close()
                stop.wait(10)
                continue
            st["state"], st["connects"] = "streaming", st["connects"] + 1
            s.settimeout(5)
            last_gga, pending = 0.0, b""
            s.sendall(rx.gga + b"\r\n")
            while not stop.is_set():
                if time.monotonic() - last_gga >= cfg.get("gga_interval_s", 1) and rx.gga:
                    s.sendall(rx.gga + b"\r\n")
                    last_gga = time.monotonic()
                data = s.recv(4096)
                if not data:
                    raise ConnectionError("caster closed the connection")
                rx.write(data)
                st["bytes"] += len(data)
                st["last_data"] = time.monotonic()
                pending = rtcm_frames(pending + data, st["types"])
        except (OSError, ConnectionError) as e:
            st["state"] = f"reconnecting ({e})"
            stop.wait(3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--rtcm-port", default=None,
                    help="send RTCM out of this UART instead of --port (e.g. /dev/ttyAMA4, pin 32)")
    ap.add_argument("--rtcm-baud", type=int, default=None, help="baud for --rtcm-port (default: --baud)")
    ap.add_argument("--config", default=os.path.expanduser("~/.config/ntrip.json"))
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    rx = Receiver(a.port, a.baud, a.rtcm_port, a.rtcm_baud)
    st = {"state": "starting", "bytes": 0, "connects": 0, "last_data": 0.0, "types": collections.Counter()}
    stop = threading.Event()
    threading.Thread(target=ntrip, args=(cfg, rx, st, stop), daemon=True).start()
    print(f"NTRIP {cfg['host']}:{cfg['port']}/{cfg['mountpoint']} -> {a.rtcm_port or a.port} @ {a.baud} "
          f"(NMEA from {a.port})", flush=True)
    t0, last_b, first_fix = time.monotonic(), 0, {}
    try:
        while not a.seconds or time.monotonic() - t0 < a.seconds:
            time.sleep(2)
            f = rx.gga.decode(errors="replace").split("*")[0].split(",") if rx.gga else []
            q = f[6] if len(f) > 6 else "?"
            el = time.monotonic() - t0
            if q not in first_fix:
                first_fix[q] = el
            rate = (st["bytes"] - last_b) / 2
            last_b = st["bytes"]
            types = " ".join(f"{k}x{v}" for k, v in sorted(st["types"].items()))
            print(f"{el:6.0f}s  {FIX.get(q, q):10s} sats {f[7] if len(f) > 7 else '?':>2s} HDOP {f[8] if len(f) > 8 else '?':>5s} "
                  f"age {f[13] if len(f) > 13 and f[13] else '-':>4s} base {f[14] if len(f) > 14 and f[14] else '-':>4s} | "
                  f"{st['state']}, {rate:.0f} B/s | RTCM {types}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        rx.stop.set()
        print("time to each fix type: " + ", ".join(f"{FIX.get(k, k)} {v:.0f} s" for k, v in first_fix.items()), flush=True)


if __name__ == "__main__":
    main()
