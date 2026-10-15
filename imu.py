#!/usr/bin/env python3
"""
Minimal BNO085 reader over SPI on a Raspberry Pi 5.

Wiring (Pi header):  BNO085 VIN -> pin 17 (3V3)
                     BNO085 GND -> pin 20 (GND)
                     BNO085 SCL -> pin 23 (GPIO11 / SCK)
                     BNO085 SDA -> pin 21 (GPIO9 / MISO)
                     BNO085 DI  -> pin 19 (GPIO10 / MOSI)
                     BNO085 CS  -> pin 24 (GPIO8, driven as a plain GPIO)
                     BNO085 INT -> pin 22 (GPIO25)
                     BNO085 RST -> pin 18 (GPIO24)
                     BNO085 P0  -> pin 16 (GPIO23, WAKE; held high through reset)
                     BNO085 P1  -> 3V3 (P0 and P1 both high at reset = SPI mode)
INT is read with libgpiod edge events (python3-libgpiod), not polled: the process sleeps until
the chip pulls INT low, and each event carries a kernel timestamp. A watchdog hard-resets the
chip if samples stop (it can stop signalling INT for good if INT isn't serviced in time).
Requires: dtoverlay=spi0-0cs in /boot/firmware/config.txt (SPI0 with CS left to us)
          pip install adafruit-circuitpython-bno08x adafruit-blinka
Usage:    .venv/bin/python imu.py [--hz 100] [--rt 80]
"""
import argparse
import math
import subprocess
import time
from struct import pack_into

import board
import busio
import digitalio
import gpiod
from gpiod.line import Bias, Direction, Edge, Value
from adafruit_bno08x import (
    BNO_REPORT_ACCELEROMETER,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_ROTATION_VECTOR,
    Packet,
    PacketError,
)
from adafruit_bno08x.spi import BNO08X_SPI


def channel_is_data(packet):
    """Startup traffic on channels 0/1 (advertisement, reset complete) isn't for the report parser."""
    return packet.channel_number > 1


INT_GPIO = 25                 # BNO085 INT -> pin 22
GPIOCHIP = "/dev/gpiochip0"   # pinctrl-rp1 (the 40-pin header) on Pi 5


class GpiodInt:
    """BNO085 INT line via libgpiod, with falling-edge events instead of polling.

    Stands in for the DigitalInOut the driver expects (.value, switch_to_input, deinit).
    Blinka can't also open GPIO25: it claims lines through lgpio, and a line has one owner.
    """

    def __init__(self, gpio=INT_GPIO, chip=GPIOCHIP):
        self._gpio = gpio
        self._req = gpiod.request_lines(chip, consumer="bno085-int", config={gpio: gpiod.LineSettings(
            direction=Direction.INPUT, edge_detection=Edge.FALLING, bias=Bias.PULL_UP)})
        self.last_edge_ns = None      # CLOCK_MONOTONIC time of the latest falling edge

    @property
    def value(self):
        return self._req.get_value(self._gpio) == Value.ACTIVE

    def switch_to_input(self, pull=None):
        pass                          # always an input with pull-up (set at request time)

    def _drain(self):
        for ev in self._req.read_edge_events():
            self.last_edge_ns = ev.timestamp_ns

    def wait_low(self, timeout):
        """Sleep until INT is low (data ready) or `timeout` s pass. Returns True if INT is low."""
        deadline = time.monotonic() + timeout
        while self.value:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._req.wait_edge_events(remaining):
                self._drain()
        return True

    def deinit(self):
        self._req.release()


class PiBNO08X_SPI(BNO08X_SPI):
    """adafruit_bno08x's SPI transport, fixed for the Pi 5.

    The stock driver doesn't work here:
    - Blinka only switches spidev to mode 3 inside the first transfer, after CS is already low,
      so SCLK rises with CS asserted and every bit of that first read is shifted by one.
    - It reads the 4-byte header and the packet in two CS transactions; the chip counts the
      first as a truncated read and sends the rest as a continuation.
    - It waits for INT before writing. With nothing pending INT never comes, so it hard-resets
      the chip. The BNO08x only takes a write while INT is asserted; WAKE (P0) asks for that.
    - Its _data_ready blocks for up to 3 s and resets on timeout instead of just checking INT.
    """

    def __init__(self, spi_bus, cspin, intpin, resetpin, wakepin, baudrate=1_000_000, debug=False):
        self._wake = wakepin
        self._wake.switch_to_output(value=True)
        super().__init__(spi_bus, cspin, intpin, resetpin, baudrate=baudrate, debug=debug)

    def _wait_int(self, timeout):
        return self._int.wait_low(timeout)

    @property
    def _data_ready(self):
        return not self._int.value

    def hard_reset(self):
        self._int.switch_to_input(pull=digitalio.Pull.UP)
        self._reset.switch_to_output(value=True)
        self._wake.value = True             # PS0 must be high when RST rises to select SPI
        dev = self._spi
        while not dev.spi.try_lock():
            pass
        try:                                # park SCLK at its mode-3 idle level while CS is high
            dev.spi.configure(baudrate=dev.baudrate, polarity=1, phase=1)
            dev.spi.write(b"\0")
        finally:
            dev.spi.unlock()
        self._reset.value = False
        time.sleep(0.01)
        self._reset.value = True
        if not self._wait_int(1.0):
            raise RuntimeError("BNO085 never asserted INT after reset (check INT, RST, P0/P1 wiring)")

    def soft_reset(self):
        """Drain the startup packets (advertisement, init response, reset complete)."""
        start = time.monotonic()
        while time.monotonic() - start < 0.3:
            if self._data_ready:
                start = time.monotonic()
                self._transfer()
            else:
                time.sleep(0.005)

    def _transfer(self, out=None):
        """One full-duplex CS transaction: send `out` (if any), receive whatever packet is pending."""
        out_len = len(out) if out else 0
        hdr_in = bytearray(4)
        with self._spi as spi:
            spi.write_readinto(bytearray(out[:4]) if out else bytearray(4), hdr_in)
            in_len = (hdr_in[0] | hdr_in[1] << 8) & 0x7FFF
            total = max(in_len, out_len)
            if total > len(self._data_buffer):
                self._data_buffer = bytearray(total)
            buf = self._data_buffer
            buf[0:4] = hdr_in
            if total > 4:
                tx = bytearray(total - 4)
                if out:
                    tx[: out_len - 4] = out[4:]
                rx = bytearray(total - 4)
                spi.write_readinto(tx, rx)
                buf[4:total] = rx
        if in_len <= 4 or hdr_in[1] & 0x80:   # nothing pending, or an orphaned continuation
            return None
        packet = Packet(buf)
        self._update_sequence_number(packet)
        return packet

    def _handle_packet(self, packet):
        # Command-channel packets (0/1) can arrive mid-stream; the stock parser raises
        # "Unprocessable Batch bytes" on them, which would end the read loop.
        if channel_is_data(packet):
            super()._handle_packet(packet)

    def _read_packet(self):
        if not self._data_ready:
            raise PacketError("No packet available")
        packet = self._transfer()
        if packet is None:
            raise PacketError("No packet available")
        return packet

    def _send_packet(self, channel, data):
        out = bytearray(len(data) + 4)
        pack_into("<H", out, 0, len(out))
        out[2] = channel
        out[3] = self._sequence_number[channel]
        out[4:] = data
        if not self._data_ready:
            self._wake.value = False
            ok = self._wait_int(0.2)
            self._wake.value = True
            if not ok:
                raise RuntimeError("BNO085 ignored WAKE (check P0 -> GPIO23)")
        packet = self._transfer(out)
        self._sequence_number[channel] = (self._sequence_number[channel] + 1) % 256
        if packet is not None and channel_is_data(packet):   # the chip sent us a packet during our write
            try:
                self._handle_packet(packet)
            except Exception:
                pass
        return self._sequence_number[channel]


def quat_to_euler(i, j, k, real):
    """Quaternion -> (roll, pitch, yaw) in degrees."""
    roll = math.atan2(2 * (real * i + j * k), 1 - 2 * (i * i + j * j))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (real * j - k * i))))
    yaw = math.atan2(2 * (real * k + i * j), 1 - 2 * (j * j + k * k))
    return tuple(math.degrees(a) for a in (roll, pitch, yaw))


def recover_bus(sda=2, scl=3):
    """Free the I2C bus if a device is holding SDA low (e.g. the BNO085 reset mid-transfer).

    Clocks SCL until SDA is released, sends a STOP, then hands the pins back to I2C.
    Returns True if the bus was stuck. Must not run while another I2C transfer is active.
    """
    def pinctrl(*args):
        return subprocess.run(["pinctrl", *map(str, args)], capture_output=True, text=True).stdout.strip()

    if pinctrl("lev", sda) == "1":
        return False
    for _ in range(18):
        pinctrl("set", scl, "op", "dl")
        pinctrl("set", scl, "op", "dh")
        if pinctrl("lev", sda) == "1":
            break
    pinctrl("set", sda, "op", "dl")      # STOP: SDA rises while SCL is high
    pinctrl("set", scl, "op", "dh")
    pinctrl("set", sda, "op", "dh")
    pinctrl("set", f"{sda},{scl}", "a3", "pu")
    return True


DEFAULT_REPORTS = (BNO_REPORT_ACCELEROMETER, BNO_REPORT_GYROSCOPE, BNO_REPORT_ROTATION_VECTOR)


def open_imu(reports=DEFAULT_REPORTS, interval_us=50_000, baudrate=1_000_000):
    """Open the BNO085 on SPI0 and enable `reports`. Release with close_imu()."""
    spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    cs, rst, wake = (digitalio.DigitalInOut(p) for p in (board.D8, board.D24, board.D23))
    hw = [spi, cs, rst, wake]
    try:
        irq = GpiodInt()
        hw.append(irq)
        bno = PiBNO08X_SPI(spi, cs, irq, rst, wake, baudrate=baudrate)   # hard-resets via RST
    except Exception:
        _release(hw)
        raise
    bno._hw = hw
    bno._enabled = (tuple(reports), interval_us)
    enable_reports(bno, reports, interval_us)
    return bno


def recover_imu(bno):
    """Hard-reset a BNO085 that stopped sending (INT went quiet) and re-enable its reports."""
    bno._readings.clear()
    bno.initialize()                  # hard reset + drain startup packets + check ID
    enable_reports(bno, *bno._enabled)


def enable_reports(bno, reports, interval_us):
    for report in reports:
        # The BNO08x often drops the first enable while it's still sending startup packets.
        for attempt in range(5):
            try:
                bno.enable_feature(report, report_interval=interval_us)
                break
            except RuntimeError:
                if attempt == 4:
                    raise
                time.sleep(0.2)


def _release(hw):
    for dev in hw:
        try:
            dev.deinit()
        except Exception:
            pass


def close_imu(bno):
    """Free the SPI bus and GPIOs so open_imu() can be called again."""
    _release(getattr(bno, "_hw", ()))


def wait_sample(bno, timeout):
    """Block until INT asserts, then read everything pending. Returns False on timeout."""
    if not bno._int.wait_low(timeout):
        return False
    bno._process_available_packets()
    return True


class Watchdog:
    """Hard-resets the BNO085 if no rotation-vector sample arrives for `timeout` s."""

    def __init__(self, bno, timeout=0.2):
        self.bno, self.timeout = bno, timeout
        self.last = time.monotonic()
        self.resets = 0

    def fed(self):
        self.last = time.monotonic()

    def remaining(self):
        return max(0.0, self.last + self.timeout - time.monotonic())

    def check(self):
        """Call when a wait timed out; resets the chip if it has been silent too long."""
        if time.monotonic() - self.last < self.timeout:
            return False
        self.resets += 1
        recover_imu(self.bno)
        self.last = time.monotonic()
        return True


def main():
    ap = argparse.ArgumentParser(description="Print BNO085 readings as soon as each sample arrives.")
    ap.add_argument("--hz", type=float, default=100, help="report rate to request (default %(default)s, max ~200)")
    ap.add_argument("--watchdog", type=float, default=0.2, help="reset the chip after this many s without data")
    ap.add_argument("--rt", type=int, default=0, help="SCHED_FIFO priority (needs rtprio limit or root)")
    args = ap.parse_args()
    if args.rt:
        import rt_tune
        rt_tune.apply(rt_prio=args.rt)

    bno = open_imu(interval_us=int(1e6 / args.hz))
    dog = Watchdog(bno, args.watchdog)
    n, t0, rate = 0, time.monotonic(), 0.0
    try:
        while True:
            # Service INT promptly: if it isn't answered within ~10 ms the BNO085 stops signalling.
            if not wait_sample(bno, dog.remaining() or 0.001):
                if dog.check():
                    print(f"no data for {args.watchdog} s: BNO085 reset (#{dog.resets})")
                continue
            q = bno._readings.pop(BNO_REPORT_ROTATION_VECTOR, None)
            if q is None:
                continue
            dog.fed()
            ax, ay, az = bno._readings.get(BNO_REPORT_ACCELEROMETER, (0.0, 0.0, 0.0))
            gx, gy, gz = bno._readings.get(BNO_REPORT_GYROSCOPE, (0.0, 0.0, 0.0))
            roll, pitch, yaw = quat_to_euler(*q)
            n += 1
            if time.monotonic() - t0 >= 1.0:
                rate, n, t0 = n / (time.monotonic() - t0), 0, time.monotonic()
            print(f"accel[m/s^2] {ax:7.2f} {ay:7.2f} {az:7.2f} | "
                  f"gyro[rad/s] {gx:6.2f} {gy:6.2f} {gz:6.2f} | "
                  f"rpy[deg] {roll:7.1f} {pitch:7.1f} {yaw:7.1f} | {rate:4.0f} Hz")
    except KeyboardInterrupt:
        pass
    finally:
        close_imu(bno)


if __name__ == "__main__":
    main()
