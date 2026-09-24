#!/usr/bin/env python3
"""
Minimal BNO085 reader over I2C on a Raspberry Pi.

Wiring (Pi header):  BNO085 VIN -> pin 1 (3V3)
                     BNO085 GND -> pin 9 (GND)
                     BNO085 SDA -> pin 3 (GPIO2 / SDA1)
                     BNO085 SCL -> pin 5 (GPIO3 / SCL1)
Requires: dtparam=i2c_arm=on in /boot/firmware/config.txt
          pip install adafruit-circuitpython-bno08x adafruit-blinka
Usage:    python3 imu.py
"""
import math
import subprocess
import time

import board
import busio
from adafruit_bno08x import (
    BNO_REPORT_ACCELEROMETER,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_ROTATION_VECTOR,
)
from adafruit_bno08x.i2c import BNO08X_I2C


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


def open_imu(address=0x4A, reports=DEFAULT_REPORTS, interval_us=50_000):
    i2c = busio.I2C(board.SCL, board.SDA)   # bus speed comes from dtparam i2c_arm_baudrate
    bno = BNO08X_I2C(i2c, address=address)
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
    return bno


def main():
    bno = open_imu()
    while True:
        ax, ay, az = bno.acceleration
        gx, gy, gz = bno.gyro
        roll, pitch, yaw = quat_to_euler(*bno.quaternion)
        print(f"accel[m/s^2] {ax:7.2f} {ay:7.2f} {az:7.2f} | "
              f"gyro[rad/s] {gx:6.2f} {gy:6.2f} {gz:6.2f} | "
              f"rpy[deg] {roll:7.1f} {pitch:7.1f} {yaw:7.1f}")
        time.sleep(0.05)


if __name__ == "__main__":
    main()
