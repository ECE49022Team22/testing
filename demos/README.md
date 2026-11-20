# demos/: one short script per requirement

Each script shows one thing the TAs check, prints plain numbers, and is short enough to read on screen in a minute.
(`demo/`, without the s, is the separate live dashboard.)

**Before running any of them**, stop the robot program, which otherwise holds the serial ports:

```bash
sudo systemctl stop cosmo-robot
cd ~/testing
```

**Wheels off the ground** for `speed_control.py`, `command_timeout.py` and `serial_link.py`.

| Script | Requirement | What it shows |
|---|---|---|
| `.venv/bin/python demos/lidar_rate.py` | 6-1 | LiDAR scans per second, points per scan, 360° coverage, nearest/farthest return |
| `.venv/bin/python demos/lidar_obstacle.py` | 6-2, 8-1 | Distance to the nearest thing ahead, live; "OBSTACLE" under 1 m |
| `.venv/bin/python demos/encoders.py` | 4-1 | Encoder counts and wheel turns while you turn a wheel by hand |
| `.venv/bin/python demos/speed_control.py` | 4-2 | Steps 60 → 120 → 60 → 0 → −60 → 0 rpm: target vs measured speed and duty, time to settle |
| `.venv/bin/python demos/speed_control.py hold 60` | 4-2 | Holds 60 rpm: press on a tyre and the duty rises while the speed holds |
| `.venv/bin/python demos/command_timeout.py` | 4-3 | Pi stops sending commands; the microcontroller zeroes the targets by itself (~400 ms) |
| `.venv/bin/python demos/serial_link.py` | 4-4, UART link | A command and its reply, command and telemetry rates, a corrupted command refused |
| `.venv/bin/python demos/imu_spi.py` | 5-2 | IMU samples per second over SPI, turn rate, heading while you turn the robot |
| `.venv/bin/python demos/gps.py --rtk` | 5-1, 5-3, 5-5 | Fixes per second, fix type (RTK float/fixed), satellites; reports the loss when the antenna is covered |
| `.venv/bin/python demos/latch.py` | 11-3, 11-4 | Latch opens and closes on command; the microcontroller reports the servo position |

When you're done: `sudo systemctl start cosmo-robot`.

If a motor demo is stopped half-way, the motors stop by themselves: the firmware's command watchdog zeroes them 400 ms
after the last command, and every script also sends `stop` when it exits.
