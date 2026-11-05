# Live demo: every sensor at once

Runs the robot's sensor apps concurrently, each as its own process with the core and real-time
priority from the benchmark (`bench/final.toml`), and shows them live in a browser. It's meant to show
that the optimizations let the latency-critical streams run in parallel without missing deadlines,
and to let you switch back to the original setup to see the difference.

```bash
cd ~/testing/demo
python3 run_demo.py                     # optimized (final system)
python3 run_demo.py --browser           # same, and open the dashboard on the Pi's screen
python3 run_demo.py --profile cpu       # best setup before the AI HAT+ (YOLO on the CPU)
python3 run_demo.py --profile baseline  # how it started: no pinning, no RT, PyTorch, queued camera
python3 run_demo.py --motor-rpm 5       # hold both wheels at 5 RPM forward instead of 0 (they WILL turn)
python3 run_demo.py --motor-max-rpm 60  # dashboard motor controls limited to ±60 RPM per wheel (default ±175)
python3 run_demo.py --right-sign 1      # right motor NOT mounted mirrored (see "Wheels" below)
python3 run_demo.py --left-motor 1      # swap which STM32 motor is the left wheel (default 2)
python3 run_demo.py --no-motor-control  # dashboard shows the motor but cannot drive it
python3 run_demo.py --motor-port /dev/ttyAMA3   # STM32 on a direct UART instead of the USB-serial adapter
```

Open `http://localhost:8090/` on the Pi, or `http://<pi-address>:8090/` from a laptop on the same network.
A laptop is the better choice for a demo: a browser on the Pi itself competes for the CPU. `--browser`
limits that by pinning its Chromium window to core 0 at low priority, in a separate profile.
Ctrl-C stops everything.

## What it shows

| tile | source | live numbers |
|---|---|---|
| Stop-sign detection | USB camera → Hailo-8L (or CPU) | annotated video, frames/s, capture → detection, 3-frame confirmation |
| Deadlines | all streams | each stream's p99 and worst case against its budget, share of time on budget |
| IMU | BNO085, SPI0 | horizon, interrupt → serviced latency, sample period, late samples, watchdog resets |
| LiDAR | STL-27L, UART2 (pin 29) | top-down scan, delivery latency, CRC errors |
| GPS | UM982, UART0 + PPS | fix, satellites, position, timing vs the 5 Hz grid, PPS |
| Cores and processes | `/proc` | per-core load by role; each process's allowed cores, where it ran, scheduling class, CPU, preemptions |
| Cellular | the receiver's log | Notehub session, signal, events |
| Drive motors | STM32, two PG27s, over its serial link (`--motor-port`, default `/dev/ttyUSB0`) | per wheel: target vs measured RPM, duty, cap, encoder, faults, and a top view of the robot; command → acknowledgement latency; telemetry rate and delivery |

Measured on 2026-10-19 (camera pointed at the room, no stop sign; LiDAR not delivering packets):

| profile | capture → detection p50 / p99 | frames/s | IMU late samples | IMU interrupt max |
|---|---|---|---|---|
| baseline | 690 / 753 ms | 2.0 | 33 in ~20 s | 5.0 ms |
| cpu | 163 / 231 ms | 9.5 | 1 | 1.1 ms |
| optimized | 51 / 60 ms | 30 | 0 | ~0.6 ms |

## What it touches, and what it doesn't

- **STM32 / motors:** `d_motor.py` sends only the two wheel targets (`d <rpm1> <rpm2>`), **0 unless you pass `--motor-rpm N`
  or drive from the dashboard**, 20 times a second, each clamped to ±`--motor-max-rpm` (default 175, below the ~195 RPM full-duty
  limit), and times the "OK" reply (p99 ~13 ms with two motors: an ack waits behind the ~13 ms two-motor telemetry line). While it runs, telemetry is at 50 Hz (for the board's timestamps). On exit it sends `stop` and restores
  10 Hz. It never changes the duty cap, gains or open-loop mode. Close `motor_live.py` / `motor_pid_uart.py` first: only one
  program can hold the port.
- **Notecard:** never opened. `receive_demo.py` (tmux `cellular`, started by cron) owns the I2C bus, and the demo
  only reads its log.
- **Motor controls in the browser** (Drive motors tile): a hold-to-drive pad (**Forward**, **Back**, **Turn left**, **Turn
  right**, or the arrow keys / WASD) with drive and turn speed sliders, a slider per wheel with **Run both**, **Stop** and
  **Clear stall faults**. Turning spins in place: turn left = left wheel back, right wheel forward. The page POSTs
  `{"drive": [left, right]}` to the hub's `/motor`, which passes it to `d_motor.py` on localhost UDP 8766. A dashboard target
  is a 1 s lease that the page renews every 300 ms: letting go of the pad, closing or hiding the tab, pressing Esc, or losing
  the network brings the motors back to the command-line target (0) within a second (the firmware itself would hold its
  last targets forever). Anyone who can open the page can drive the robot; `--no-motor-control` turns the controls off.
  Nothing else in the hub changes anything.
- **Wheels:** left = STM32 motor 2 (MDD20A channel 2), right = motor 1 (channel 1), checked driving on the floor
  (2026-11-04: speeding up motor 1 turned the robot left); `--left-motor 1` swaps them. Targets are in the robot's frame
  (+ = forward): motor 1's + direction rolls the robot backward and motor 2's forward, so the defaults are
  `--left-motor 2 --left-sign 1 --right-sign -1`. If the motors are re-plugged, check again: if **Forward** spins the
  robot, flip one sign; if it drives backward, flip both; if the turn buttons turn the wrong way, swap `--left-motor`.
  Wheel speed is capped at ±175 RPM (`--motor-max-rpm`): with the wheels on, 100% duty gives ~195 RPM, so that leaves
  the PID ~10% headroom. The chassis is skid-steer (two driven and two unpowered wheels), so turns are much wider than
  the wheel speeds suggest: effective track ~1 m, not the 50 cm between the wheels, and spinning in place stalls.

## How it works

```
 core 1 (isolated, RT)        cores 2-3                    core 0
 d_imu.py   FIFO 49 ─┐        d_vision.py ──── MJPEG :8091 ──────────────┐
 d_motor.py FIFO 48 ─┤                                                   │
 d_lidar.py FIFO 47 ─┼─ UDP ─────────────┐                               │
 d_gps.py   FIFO 46 ─┘  (localhost 8765, │    d_cell.py ── UDP ─┐        │
                         never blocks)   └──────────────────────┴─ hub.py ── HTTP :8090 + SSE ── browser
```

- Workers send small JSON datagrams with non-blocking `sendto()`, so a slow or closed dashboard can't delay a
  real-time loop. Annotated video is encoded in its own thread at ≤ 15 fps and only while someone watches.
  Encoding inside the detection loop had added up to 60 ms of latency.
- RT priorities stay below 50, so the kernel threads that deliver the sensors' interrupts (SCHED_FIFO 50) run first
  (see `bench/ROUND3_AI_HAT.md`, "priority inversion").
- A worker whose device is missing shows "not connected" and retries every 5 s. One that crashes is restarted
  after 3 s (`logs/<name>.log`).

Files: `run_demo.py` (launcher, profiles), `hub.py` (collector + web server), `d_*.py` (one per sensor),
`bus.py` (shared messaging and stats), `static/` (the dashboard).
