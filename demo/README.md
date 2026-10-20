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
| Motor link | `/proc` only | whether `/dev/ttyUSB0` exists and who has it open |

Measured on 2026-10-19 (camera pointed at the room, no stop sign; LiDAR not delivering packets):

| profile | capture → detection p50 / p99 | frames/s | IMU late samples | IMU interrupt max |
|---|---|---|---|---|
| baseline | 690 / 753 ms | 2.0 | 33 in ~20 s | 5.0 ms |
| cpu | 163 / 231 ms | 9.5 | 1 | 1.1 ms |
| optimized | 51 / 60 ms | 30 | 0 | ~0.6 ms |

## What it does not touch

- **STM32 / motor:** never started. The demo never opens `/dev/ttyUSB0` (the hub only looks it up in `/proc`).
- **Notecard:** never opened. `receive_demo.py` (tmux `cellular`, started by cron) owns the I2C bus, and the demo
  only reads its log.
- **No controls:** the hub has no endpoints that change anything. It only serves the page and the live state.

## How it works

```
 core 1 (isolated, RT)        cores 2-3                    core 0
 d_imu.py   FIFO 49 ─┐        d_vision.py ──── MJPEG :8091 ──────────────┐
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
