#!/usr/bin/env python3
"""Configure the DATAGNSS GEM1305 (Allystar) from the Pi without Satrack: see why RTCM corrections aren't
being used, switch the receiver to RTK rover, and send DATAGNSS's .cmd files. Steps and background: GEM1305_CONFIG.md.

    .venv/bin/python gem1305_cfg.py info                     read only: version, DGNSS mode, base settings, ports, fix
    .venv/bin/python gem1305_cfg.py rover [--save]           DGNSS mode -> RTK, clear any fixed base position
    .venv/bin/python gem1305_cfg.py decode FILE.cmd          offline: list what a DATAGNSS .cmd file sends
    .venv/bin/python gem1305_cfg.py send-cmd FILE.cmd [--save]   what Satrack's Tools > Send Command does
    .venv/bin/python gem1305_cfg.py save                     keep the current settings over a power cycle
    .venv/bin/python gem1305_cfg.py poll 06 F1 [PAYLOAD_HEX]  any message by class/id, prints the raw reply

Wiring: replies are read on --port (UART0 RX, /dev/ttyAMA0) and commands go out on --tx-port (UART4 TX,
/dev/ttyAMA4, header pin 32 -> GEM1305 RX), because UART0's TX pin doesn't drive (see ntrip_rtk.py). Both at
--baud (230400, the GEM1305 default). Only one program can read the port: stop the demo's GPS worker and
ntrip_rtk.py first. --dry-run prints the frames instead of opening any port.

Protocol, taken from Satrack v1.31.007's own code (its native frame builder was run in an emulator to produce
the test vectors in selftest()), and checked against a MON-VER reply recorded from a real receiver:
  frame = F1 D9 | class | id | length (u16 LE) | payload | 2-byte Fletcher checksum over class..payload
  A set is answered with ACK-ACK (05 01) or ACK-NAK (05 00) whose payload is [class, id]. A poll is the
  message with an empty payload (CFG-PRT: the port number), answered with the same message.
  MON-VER       0A 04  reply: software[16] hardware[16], ASCII, NUL padded
  CFG-DGNSS     06 F1  [mode u8][pre-filter u8]; mode 0 none, 1 SBAS, 2 RTD (code), 3 RTK float, 4 RTK fixed
  CFG-SURVEY    06 12  [min duration s u32][accuracy limit mm u32]   (survey-in: base-station setup)
  CFG-FIXEDLLA  06 13  [lat 1e-7 deg i32][lon 1e-7 deg i32][alt cm i32]
  CFG-FIXEDECEF 06 14  [X cm i32][Y cm i32][Z cm i32]; Satrack's Clear button sends all zero
  CFG-PRT       06 00  poll [port 0|1] -> [port u8][3 reserved][baud u32]
  CFG-CFG       06 09  [action u32: 0 save, 1 load, 2 clear][sections u32: 1 baud, 2 messages, 4 nav;
                       0xFFFFFFFF is Satrack's "Factory Reset"]. Satrack's own "Set RTK rate" saves with 3.
Untested against the GEM1305 itself: check `info` first, and it only changes settings when asked to.
"""
import argparse
import queue
import re
import struct
import sys
import threading
import time

SYNC = b"\xf1\xd9"
MON_VER, CFG_DGNSS, CFG_SURVEY = (0x0A, 0x04), (0x06, 0xF1), (0x06, 0x12)
CFG_FIXEDLLA, CFG_FIXEDECEF, CFG_PRT, CFG_CFG = (0x06, 0x13), (0x06, 0x14), (0x06, 0x00), (0x06, 0x09)
ACK_NAK, ACK_ACK = (0x05, 0x00), (0x05, 0x01)
DGNSS_MODES = {0: "none: corrections are ignored", 1: "SBAS only", 2: "RTD (code differential only)",
               3: "RTK float", 4: "RTK fixed"}
SAVE_SECTIONS = 0x1 | 0x2 | 0x4          # baud, messages, nav: Satrack's "Set RTK rate" saves 3; nav is added for DGNSS
GGA_FIX = {"0": "no fix", "1": "GPS", "2": "DGPS", "4": "RTK fixed", "5": "RTK float", "6": "dead reckoning"}

# (class, id) -> name, from Satrack's message panels
NAMES = {
    (0x01, 0x01): "NAV-POSECEF", (0x01, 0x02): "NAV-POSLLH", (0x01, 0x03): "NAV-STATUS", (0x01, 0x04): "NAV-DOP",
    (0x01, 0x05): "NAV-TIME", (0x01, 0x06): "NAV-POSECEFX", (0x01, 0x07): "NAV-POSLLHX", (0x01, 0x11): "NAV-VELECEF",
    (0x01, 0x12): "NAV-VELNED", (0x01, 0x21): "NAV-TIMEUTC", (0x01, 0x22): "NAV-CLOCK", (0x01, 0x23): "NAV-CLOCK2",
    (0x01, 0x26): "NAV-PVERR", (0x01, 0x30): "NAV-SVINFO", (0x01, 0x31): "NAV-SVIN", (0x01, 0x32): "NAV-SVSTATE",
    (0x01, 0xC0): "NAV-AUTO", (0x01, 0xC1): "NAV-AHTS", (0x01, 0xC2): "NAV-PVT", (0x02, 0x01): "RXM-DUMPRAW",
    (0x02, 0x03): "RXM-BATCH", (0x05, 0x00): "ACK-NAK", (0x05, 0x01): "ACK-ACK", (0x06, 0x00): "CFG-PRT",
    (0x06, 0x01): "CFG-MSG", (0x06, 0x06): "CFG-DAT", (0x06, 0x07): "CFG-PPS", (0x06, 0x09): "CFG-CFG",
    (0x06, 0x0A): "CFG-DOP", (0x06, 0x0B): "CFG-ELEV", (0x06, 0x0C): "CFG-NAVSAT", (0x06, 0x0D): "CFG-HEIGHT",
    (0x06, 0x0E): "CFG-SBAS", (0x06, 0x0F): "CFG-SPDHOLD", (0x06, 0x10): "CFG-EPHSAVE", (0x06, 0x11): "CFG-NUMSV",
    (0x06, 0x12): "CFG-SURVEY", (0x06, 0x13): "CFG-FIXEDLLA", (0x06, 0x14): "CFG-FIXEDECEF",
    (0x06, 0x15): "CFG-ANTIJAM", (0x06, 0x16): "CFG-BDGEO", (0x06, 0x17): "CFG-CARRSMOOTH",
    (0x06, 0x18): "CFG-GEOFENCE", (0x06, 0x20): "CFG-RFAGCMODE", (0x06, 0x21): "CFG-ANTIJAMSCAN",
    (0x06, 0x22): "CFG-ANTISPOOF", (0x06, 0x23): "CFG-FIXEDLLAX", (0x06, 0x24): "CFG-FIXEDECEFX",
    (0x06, 0x26): "CFG-BATCH", (0x06, 0x27): "CFG-KEEPALIVE", (0x06, 0x40): "CFG-SIMPLERST",
    (0x06, 0x41): "CFG-SLEEP", (0x06, 0x42): "CFG-PWRCTL", (0x06, 0x43): "CFG-NMEAVER", (0x06, 0x44): "CFG-PWRCTL2",
    (0x06, 0x45): "CFG-SLEEP2", (0x06, 0x50): "CFG-FWUP", (0x06, 0x54): "CFG-CHANNEL", (0x06, 0x55): "CFG-CAN",
    (0x06, 0x56): "CFG-SD", (0x06, 0x58): "CFG-BYPASSCOM", (0x06, 0x5F): "CFG-USERTOBOOT",
    (0x06, 0x60): "CFG-FUSTART", (0x06, 0x61): "CFG-FUSRAW", (0x06, 0x62): "CFG-IMUMAP", (0x06, 0x66): "CFG-MODULE",
    (0x06, 0x67): "CFG-QXWZACOUNT", (0x06, 0xA0): "CFG-METEO41B", (0x06, 0xA1): "CFG-MSGALL",
    (0x06, 0xF0): "CFG-ENG", (0x06, 0xF1): "CFG-DGNSS", (0x06, 0xF2): "CFG-BLCONST", (0x0A, 0x04): "MON-VER",
    (0x0A, 0x05): "MON-INFO", (0x0A, 0x06): "MON-BIT", (0x0A, 0x07): "MON-CLIENT", (0x0A, 0x08): "MON-TRKCHAN",
    (0x0A, 0x09): "MON-RCVCLK", (0x0A, 0x0A): "MON-CWI", (0x0A, 0x0B): "MON-RRS", (0x0A, 0x12): "MON-BATCH",
    (0x0A, 0x20): "MON-PRODFLAG", (0x0B, 0x01): "AID-INI", (0x0B, 0x02): "AID-POSTIME", (0x0B, 0x03): "AID-CLKD",
    (0x0B, 0x10): "AID-POS", (0x0B, 0x11): "AID-TIME", (0x0B, 0x22): "AID-PALM_GPS", (0x0B, 0x23): "AID-PALM_BDS",
    (0x0B, 0x24): "AID-PALM_GLN", (0x0B, 0x25): "AID-PALM_GAL", (0x0B, 0x26): "AID-PALM_QZSS",
    (0x0B, 0x30): "AID-ALM", (0x0B, 0x31): "AID-EPH", (0x0B, 0x32): "AID-PEPH_GPS", (0x0B, 0x33): "AID-PEPH_BD",
    (0x0B, 0x34): "AID-PEPH_GL", (0x0B, 0x35): "AID-PEPH_GA", (0x0B, 0x36): "AID-PEPH_QZ",
    (0x0B, 0x41): "AID-STATUS", (0x0C, 0x01): "SNSR-MODE", (0x0C, 0x02): "SNSR-CACC", (0x0C, 0x03): "SNSR-CGYRO",
    (0x0C, 0x04): "SNSR-RBIAS", (0xF0, 0x00): "BOOT-RFF", (0xF0, 0x01): "BOOT-PLL", (0xF0, 0x02): "BOOT-DIV",
    (0xF0, 0x04): "BOOT-YMODEM", (0xF0, 0x05): "BOOT-YMODEM", (0xF0, 0x06): "BOOT-START",
    (0xF0, 0x07): "BOOT-VALIFLASHID", (0xF0, 0x09): "BOOT-YMODEM", (0xF0, 0x10): "BOOT-VALIFLASHREAD",
    (0xF0, 0x11): "BOOT-VALIRFACQ", (0xF0, 0x12): "BOOT-VALIRFSIN", (0xF0, 0x13): "BOOT-VALIGPIO",
    (0xF1, 0x01): "FIX-READFW", (0xF1, 0x03): "FIX-POWER", (0xF4, 0x00): "BOOT3-RFF", (0xF4, 0x01): "BOOT3-PLL",
    (0xF4, 0x02): "BOOT2-DIV",
}


def name(cls, mid):
    return NAMES.get((cls, mid), f"{cls:02X}-{mid:02X}")


def fletcher(body):
    a = b = 0
    for x in body:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return bytes((a, b))


def frame(msg, payload=b""):
    body = bytes(msg) + struct.pack("<H", len(payload)) + payload
    return SYNC + body + fletcher(body)


class Parser:
    """Splits the receiver's byte stream into binary frames and NMEA lines (they arrive interleaved)."""

    MAX_LEN = 4096

    def __init__(self):
        self.buf = b""

    def feed(self, data):
        """Returns [("frame", (cls, id), payload) | ("nmea", line) | ("raw", bytes)], keeps any partial message."""
        self.buf += data
        out, b, i = [], self.buf, 0
        while i < len(b):
            j = min((k for k in (b.find(SYNC, i), b.find(b"$", i)) if k >= 0), default=-1)
            if j < 0:
                out.append(("raw", b[i:]))
                i = len(b)
                break
            if j > i:
                out.append(("raw", b[i:j]))
                i = j
            if b.startswith(SYNC, i):
                if len(b) - i < 6:
                    break
                n = b[i + 4] | b[i + 5] << 8
                if n > self.MAX_LEN:
                    out.append(("raw", b[i:i + 1]))
                    i += 1
                    continue
                if len(b) - i < n + 8:
                    break
                body = b[i + 2:i + 6 + n]
                if fletcher(body) == b[i + 6 + n:i + 8 + n]:
                    out.append(("frame", (body[0], body[1]), bytes(body[4:])))
                    i += n + 8
                else:
                    out.append(("raw", b[i:i + 1]))
                    i += 1
            else:                                            # NMEA: up to the end of the line
                k = b.find(b"\n", i)
                if k < 0:
                    if len(b) - i > 200:                     # no line end: not NMEA after all
                        out.append(("raw", b[i:i + 1]))
                        i += 1
                        continue
                    break
                out.append(("nmea", b[i:k + 1].strip().decode("ascii", "replace")))
                i = k + 1
        self.buf = b[i:]
        return out

    def flush(self):
        rest, self.buf = self.buf, b""
        return [("raw", rest)] if rest else []


class Link:
    """The receiver: reads frames and NMEA from one serial port, writes commands to another (or the same)."""

    def __init__(self, port, tx_port, baud):
        import serial
        self.rx = serial.Serial(port, baud, timeout=0.1)
        self.tx = serial.Serial(tx_port, baud, timeout=0.1, write_timeout=2) if tx_port and tx_port != port else self.rx
        self.frames, self.gga, self.gga_t = queue.Queue(), None, 0.0
        self.stop = threading.Event()
        self.rx.reset_input_buffer()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        p = Parser()
        while not self.stop.is_set():
            try:
                data = self.rx.read(4096)
            except Exception:
                time.sleep(0.2)
                continue
            for kind, *rest in p.feed(data):
                if kind == "frame":
                    self.frames.put(tuple(rest))
                elif kind == "nmea" and rest[0][3:6] == "GGA":
                    self.gga, self.gga_t = rest[0], time.monotonic()

    def close(self):
        self.stop.set()

    def send(self, data):
        self.tx.write(data)
        self.tx.flush()

    def _wait(self, want, timeout):
        """First frame for which want(msg, payload) is true, or None after timeout."""
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                msg, payload = self.frames.get(timeout=left)
            except queue.Empty:
                return None
            if want(msg, payload):
                return msg, payload
        return None

    def _drain(self):
        while not self.frames.empty():
            self.frames.get_nowait()

    def poll(self, msg, payload=b"", timeout=1.0, tries=3):
        """Reply payload, "NAK", or None if nothing came back."""
        for _ in range(tries):
            self._drain()
            self.send(frame(msg, payload))
            r = self._wait(lambda m, p: (m == msg and len(p) > len(payload))
                           or (m == ACK_NAK and p[:2] == bytes(msg)), timeout)
            if r:
                return "NAK" if r[0] == ACK_NAK else r[1]
        return None

    def set(self, msg, payload, timeout=1.0, tries=3):
        """True on ACK-ACK, False on ACK-NAK, None if nothing came back."""
        for _ in range(tries):
            self._drain()
            self.send(frame(msg, payload))
            r = self._wait(lambda m, p: m in (ACK_ACK, ACK_NAK) and p[:2] == bytes(msg), timeout)
            if r:
                return r[0] == ACK_ACK
        return None


class DryRun:
    """Prints what would be sent; polls get no reply."""

    gga = None

    def send(self, data):
        print("   would send", data.hex(" "))

    def poll(self, msg, payload=b"", **_):
        print(f"   would poll {name(*msg)}: {frame(msg, payload).hex(' ')}")
        return None

    def set(self, msg, payload, **_):
        print(f"   would set {name(*msg)}: {frame(msg, payload).hex(' ')}")
        return "dry"

    def close(self):
        pass


def cstr(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def show_gga(link, wait=1.5):
    end = time.monotonic() + wait
    while link.gga is None and time.monotonic() < end:
        time.sleep(0.1)
    if not link.gga:
        print("NMEA:         no GGA seen on the read port")
        return
    f = link.gga.split("*")[0].split(",")
    g = lambda k: f[k] if len(f) > k and f[k] else "-"
    print(f"NMEA GGA:     fix {GGA_FIX.get(g(6), g(6))}, {g(7)} sats, HDOP {g(8)}, "
          f"correction age {g(13)}, base {g(14)}")


def no_reply(what):
    print(f"No reply to {what}. Either the commands aren't reaching the receiver (check the TX wire: Pi pin 32 to the "
          "GEM1305's RX on the same connector its TX is read from, and that /dev/ttyAMA4 exists), the replies "
          "aren't being read (another program on the read port, wrong --baud), or this firmware doesn't support it.")


def cmd_info(link, a):
    ver = link.poll(MON_VER)
    if ver is None or ver == "NAK":
        no_reply("MON-VER (the version poll)")
        show_gga(link)
        return 1
    print(f"Receiver:     software {cstr(ver[:16])}, hardware {cstr(ver[16:32])}  (commands are reaching it)")
    problems = []

    dg = link.poll(CFG_DGNSS)
    if isinstance(dg, bytes):
        mode, pre = dg[0], dg[1] if len(dg) > 1 else 0
        print(f"DGNSS mode:   {mode} = {DGNSS_MODES.get(mode, 'unknown')}  (pre-filter {pre})")
        if mode < 3:
            problems.append(f"DGNSS mode is {mode} ({DGNSS_MODES.get(mode, '?')}), so it won't compute RTK from "
                            "the corrections. `rover` sets it to RTK.")
    else:
        print(f"DGNSS mode:   {'not supported (NAK)' if dg == 'NAK' else 'no reply'}")

    base = False
    ecef = link.poll(CFG_FIXEDECEF)
    if isinstance(ecef, bytes) and len(ecef) >= 12:
        x, y, z = struct.unpack_from("<iii", ecef)
        base |= any((x, y, z))
        print("Fixed ECEF:   " + (f"X {x / 100:.2f} m, Y {y / 100:.2f} m, Z {z / 100:.2f} m" if any((x, y, z)) else "none"))
    lla = link.poll(CFG_FIXEDLLA)
    if isinstance(lla, bytes) and len(lla) >= 12:
        lat, lon, alt = struct.unpack_from("<iii", lla)
        base |= any((lat, lon, alt))
        print("Fixed LLA:    " + (f"{lat / 1e7:.7f}, {lon / 1e7:.7f}, {alt / 100:.2f} m" if any((lat, lon, alt)) else "none"))
    if base:
        problems.append("A fixed base position is set, so it is configured as a base station, which sends "
                        "corrections rather than using them. `rover` clears it.")
    sv = link.poll(CFG_SURVEY)
    if isinstance(sv, bytes) and len(sv) >= 8:
        dur, acc = struct.unpack_from("<II", sv)
        print(f"Survey-in:    minimum {dur} s, accuracy limit {acc} mm"
              + ("  (base-station survey settings; DATAGNSS's rover .cmd is the vendor's way to reset them)"
                 if dur or acc else ""))
    for port in (0, 1):
        prt = link.poll(CFG_PRT, bytes([port]))
        if isinstance(prt, bytes) and len(prt) >= 8:
            print(f"UART{port}:        {struct.unpack_from('<I', prt, 4)[0]} baud")
    show_gga(link)
    print()
    if problems:
        for p in problems:
            print("PROBLEM: " + p)
    else:
        print("No rover-blocking setting found. Next: send DATAGNSS's config_rover_5hz.cmd with send-cmd, then rerun "
              "ntrip_rtk.py outdoors.")
    return 0


def cmd_rover(link, a):
    want = {"rtd": 2, "float": 3, "fixed": 4}[a.dgnss]
    dg = link.poll(CFG_DGNSS)
    if isinstance(dg, bytes):
        pre = dg[1] if len(dg) > 1 else 0
        print(f"DGNSS mode was {dg[0]} ({DGNSS_MODES.get(dg[0], '?')})")
    elif isinstance(link, DryRun):
        pre = 0
    else:
        no_reply("CFG-DGNSS") if dg is None else print("CFG-DGNSS isn't supported (NAK)")
        return 1
    if not isinstance(dg, bytes) or dg[0] != want:
        ok = link.set(CFG_DGNSS, bytes([want, pre]))
        print(f"set DGNSS mode {want} ({DGNSS_MODES[want]}): {ack_text(ok)}")
        if ok not in (True, "dry"):
            return 1
        if not isinstance(link, DryRun):
            dg = link.poll(CFG_DGNSS)
            print(f"   now reads {dg[0] if isinstance(dg, bytes) else dg}")

    ecef = link.poll(CFG_FIXEDECEF)
    lla = link.poll(CFG_FIXEDLLA)
    fixed = any(isinstance(p, bytes) and len(p) >= 12 and any(struct.unpack_from("<iii", p)) for p in (ecef, lla))
    if fixed or isinstance(link, DryRun):
        ok = link.set(CFG_FIXEDECEF, bytes(12))                # what Satrack's Clear button sends
        print(f"clear the fixed base position: {ack_text(ok)}")
        if not isinstance(link, DryRun):
            lla = link.poll(CFG_FIXEDLLA)
            if isinstance(lla, bytes) and len(lla) >= 12 and any(struct.unpack_from("<iii", lla)):
                print("   CFG-FIXEDLLA still holds a position: try DATAGNSS's rover .cmd with send-cmd")
    else:
        print("no fixed base position set")
    if a.save:
        return cmd_save(link, a)
    print("Not saved: it lasts until the receiver loses power. Add --save, or run `save`, once RTK works.")
    return 0


def ack_text(ok):
    return {True: "ACK", False: "NAK (rejected)", None: "no reply", "dry": "dry run, not sent"}[ok]


def cmd_save(link, a):
    ok = link.set(CFG_CFG, struct.pack("<II", 0, SAVE_SECTIONS))
    print(f"save to flash (baud, messages, nav sections): {ack_text(ok)}")
    return 0 if ok in (True, "dry") else 1


def load_cmd(path):
    """A .cmd file is either hex text ("F1 D9 06 ...", what Satrack's ASCII mode reads) or raw bytes."""
    raw = open(path, "rb").read()
    try:
        tokens = raw.decode("ascii").split()
    except UnicodeDecodeError:
        tokens = []
    if tokens and all(re.fullmatch(r"(0[xX])?[0-9A-Fa-f]{1,2}", t) for t in tokens):
        return bytes(int(t, 16) for t in tokens), "hex text"
    return raw, "binary"


def is_reset(msg, payload):
    """CFG-CFG clear (action 2) or load, i.e. anything in CFG-CFG that isn't a save."""
    return msg == CFG_CFG and len(payload) >= 4 and struct.unpack_from("<I", payload)[0] != 0


def describe(msg, payload):
    n = len(payload)
    s = f"{name(*msg)} ({msg[0]:02X} {msg[1]:02X}), {n} byte{'s' * (n != 1)}" + (f": {payload.hex(' ')}" if payload else " (poll)")
    if msg == CFG_DGNSS and payload:
        s += f"  -> DGNSS mode {payload[0]} = {DGNSS_MODES.get(payload[0], '?')}"
    elif msg == CFG_CFG and len(payload) >= 8:
        act, sec = struct.unpack_from("<II", payload)
        s += f"  -> {['save', 'load', 'clear'][act] if act < 3 else act} sections 0x{sec:X}"
        if sec == 0xFFFFFFFF:
            s += " (Satrack's Factory Reset)"
    elif msg in (CFG_FIXEDECEF, CFG_FIXEDLLA) and len(payload) >= 12:
        s += "  -> clears the fixed position" if not any(struct.unpack_from("<iii", payload)) else "  -> sets a fixed base position"
    return s


def segments(data):
    p = Parser()
    return [s for s in p.feed(data) + p.flush() if s[0] != "raw" or s[1].strip(b"\r\n\0")]


def cmd_decode(link, a):
    data, kind = load_cmd(a.file)
    print(f"{a.file}: {len(data)} bytes ({kind})")
    for n, s in enumerate(segments(data), 1):
        if s[0] == "frame":
            print(f"{n:3d}. {describe(s[1], s[2])}")
        elif s[0] == "nmea":
            print(f"{n:3d}. text command {s[1]}")
        else:
            print(f"{n:3d}. {len(s[1])} other bytes: {s[1][:48].hex(' ')}{' ...' if len(s[1]) > 48 else ''}")
    return 0


def cmd_send(link, a):
    data, kind = load_cmd(a.file)
    print(f"{a.file}: {len(data)} bytes ({kind})")
    segs = segments(data)
    resets = [s for s in segs if s[0] == "frame" and is_reset(s[1], s[2])]
    if resets and not a.allow_reset:
        print("This file loads or clears the receiver's saved configuration (CFG-CFG):")
        for s in resets:
            print("   " + describe(s[1], s[2]))
        print("Nothing sent. Check it with `decode`, and add --allow-reset if that's intended.")
        return 1
    bad = 0
    for n, s in enumerate(segs, 1):
        if s[0] == "frame":
            msg, payload = s[1], s[2]
            if msg[0] == 0x06 and payload and not (msg == CFG_PRT and len(payload) == 1):
                ok = link.set(msg, payload)
                bad += ok not in (True, "dry")
                print(f"{n:3d}. {describe(msg, payload)}: {ack_text(ok)}")
            else:
                link.send(frame(msg, payload))
                print(f"{n:3d}. {describe(msg, payload)}: sent")
        else:
            text = (s[1] + "\r\n").encode() if s[0] == "nmea" else s[1]
            link.send(text)
            print(f"{n:3d}. sent {'text command ' + s[1] if s[0] == 'nmea' else f'{len(text)} other bytes'}")
        time.sleep(0.05)                                        # Satrack also paces what it sends
    if a.save and not bad:
        return cmd_save(link, a)
    if bad:
        print(f"{bad} command(s) not acknowledged: not saving.")
    return 1 if bad else 0


def cmd_poll(link, a):
    msg = (int(a.cls, 16), int(a.id, 16))
    payload = bytes.fromhex(a.payload) if a.payload else b""
    r = link.poll(msg, payload)
    print(f"{name(*msg)}: " + ("no reply" if r is None else "NAK" if r == "NAK" else f"{len(r)} bytes: {r.hex(' ')}"))
    return 0 if isinstance(r, bytes) else 1


def selftest():
    """Frames produced by Satrack's own frame builder (emulated), and a reply recorded from a receiver."""
    vectors = [(MON_VER, b"", "f1 d9 0a 04 00 00 0e 34"),
               (CFG_DGNSS, b"", "f1 d9 06 f1 00 00 f7 eb"),
               (CFG_DGNSS, bytes([4, 0]), "f1 d9 06 f1 02 00 04 00 fd e9"),
               (CFG_CFG, struct.pack("<II", 0, 7), "f1 d9 06 09 08 00 00 00 00 00 07 00 00 00 1e 17"),
               (CFG_PRT, bytes([0]), "f1 d9 06 00 01 00 00 07 21"),
               (CFG_SURVEY, b"", "f1 d9 06 12 00 00 18 4e"),
               (CFG_FIXEDLLA, b"", "f1 d9 06 13 00 00 19 51"),
               (CFG_FIXEDECEF, bytes(12), "f1 d9 06 14 0c 00" + " 00" * 12 + " 26 34")]
    for msg, payload, want in vectors:
        assert frame(msg, payload).hex(" ") == want, (name(*msg), frame(msg, payload).hex(" "), want)
    rec = bytes.fromhex("f1d90a042000332e3031382e32353634303330630000484439353130"
                        "2e3634383461663335620d4d")
    p = Parser()                                            # fed in two pieces, split mid-frame
    out = p.feed(b"\r\n$PHDANT,01*51\r\n" + rec[:9]) + p.feed(rec[9:] + b"$GNGGA,x*00\r\n")
    frames = [o for o in out if o[0] == "frame"]
    assert len(frames) == 1 and frames[0][1] == MON_VER and cstr(frames[0][2][:16]) == "3.018.2564030c", out
    assert [o[1] for o in out if o[0] == "nmea"] == ["$PHDANT,01*51", "$GNGGA,x*00"], out
    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyAMA0", help="serial port the receiver's output is read from")
    ap.add_argument("--tx-port", default="/dev/ttyAMA4",
                    help="serial port commands are written to (default %(default)s, pin 32); pass the same as --port "
                         "for a USB-serial adapter")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--dry-run", action="store_true", help="print the frames, open no port")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="read-only status")
    r = sub.add_parser("rover", help="DGNSS mode -> RTK, clear any fixed base position")
    r.add_argument("--dgnss", choices=("fixed", "float", "rtd"), default="fixed",
                   help="DGNSS mode to set (default fixed: RTK with integer ambiguity fixing)")
    r.add_argument("--save", action="store_true", help="save to flash afterwards")
    sub.add_parser("save", help="save the current settings to flash")
    d = sub.add_parser("decode", help="list the commands in a .cmd file (no serial port)")
    d.add_argument("file")
    s = sub.add_parser("send-cmd", help="send a .cmd file, checking each setting is acknowledged")
    s.add_argument("file")
    s.add_argument("--save", action="store_true", help="save to flash if every setting was acknowledged")
    s.add_argument("--allow-reset", action="store_true",
                   help="send the file even if it loads or clears the saved configuration (e.g. a factory reset)")
    p = sub.add_parser("poll", help="poll any message: CLASS ID [PAYLOAD], hex")
    p.add_argument("cls")
    p.add_argument("id")
    p.add_argument("payload", nargs="?")
    sub.add_parser("selftest", help="check the frame encoder/decoder against Satrack's own output")
    a = ap.parse_args()

    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "decode":
        return cmd_decode(None, a)
    try:
        link = DryRun() if a.dry_run else Link(a.port, a.tx_port, a.baud)
    except Exception as e:                                   # serial.SerialException, or pyserial missing
        print(f"Can't open the serial port: {e}")
        if "ttyAMA4" in str(e):
            print("UART4 needs dtoverlay=uart4-pi5 in /boot/firmware/config.txt and a reboot.")
        return 1
    try:
        return {"info": cmd_info, "rover": cmd_rover, "save": cmd_save, "send-cmd": cmd_send,
                "poll": cmd_poll}[a.cmd](link, a)
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
