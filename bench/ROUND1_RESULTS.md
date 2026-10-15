# Round 1: suggestions 3, 4, 5, 6

Three 120 s runs with all apps running together, compared with `compare.py`:

| run | what changed |
|---|---|
| `20261008_160357_baseline` | original code, LiDAR on the PIO UART (pin 15), FTDI timer 16 ms, no RT |
| `20261008_164430_fixes` | **4** IMU edge-triggered INT + watchdog, **5** LiDAR on UART2 (pin 29) + block reads + packet validation, **6** STM32 USART5 on DMA + FTDI latency timer 1 ms |
| `20261008_165047_tuned2` | fixes + **3** SCHED_FIFO (IMU 80, motor 70, LiDAR 60, GPS 50), timer slack 1 ns, mlockall (`tuned.toml`) |

## Results (p50 / p99 / max)

| | baseline | fixes | fixes + RT |
|---|---|---|---|
| IMU sample period (10 ms) | 10.0 / 17.6 / 29.8 ms | 10.0 / 17.2 / 29.0 ms | 10.1 / **12.2 / 14.3 ms** |
| IMU samples > 15 ms late | 2.6% | 2.9% | **0%** |
| IMU INT → service | ≤0.58 / ≤3.3 / ≤8.5 ms (poll bound) | 0.10 / 2.2 / 8.9 ms | **0.10 / 0.39 / 0.92 ms** |
| GPS GGA timing error | 0.33 / 3.7 / 21.2 ms | 0.34 / 5.4 / 6.5 ms | 0.14 / 3.1 / 5.2 ms |
| LiDAR delivery above best case | 0.79 / 3.7 / 11.2 ms | 2.2 / 5.5 / 13.3 ms | 1.15 / 3.6 / 8.0 ms |
| LiDAR CRC errors | 4,292 (1.9%) | 1 | **0** |
| Motor command → reply | 11.3 / 27.2 / 31.0 ms | **2.8 / 6.8 / 10.8 ms** | **2.8 / 6.4 / 10.5 ms** |
| Motor commands never answered | 20 of 2,250 | 1 | **0** |
| YOLO capture → detection | 872 / 1017 / 1062 ms | 814 / 978 / 1025 ms | 822 / 950 / 1046 ms |

| CPU (% of one core) | baseline | fixes + RT |
|---|---:|---:|
| LiDAR | 30.3 | **15.2** |
| IMU | 17.7 | 18.2 |
| YOLO | 179 | 183 |

Involuntary context switches/s (the process was preempted): IMU 3,321 → 2, LiDAR 1,091 → 8, motor 62 → 0.

## What each change did

- **6 Motor link:** the biggest single win. The FTDI timer accounted for most of the round trip (11.3 → 2.8 ms median),
  and DMA receive removed the dropped commands (it handled 1,000/1,000 in a separate 50 Hz stress test). On its own,
  real-time priority adds little here.
- **5 LiDAR:** on the hardware UART, CRC errors went to zero, and block reads halved its CPU. The cost of block reads: the median
  delivery delay rises ~1–1.5 ms, because the reader now waits for 188 bytes (4 packets). Pass `--min-read 94` (or 47) to
  trade some of that back for more wakeups.
- **4 IMU:** edge events made INT service fast in the typical case (0.10 ms). But with YOLO competing for CPU, the IMU was
  still preempted. Only real-time priority fixed the tail: no late samples, worst INT service 0.92 ms (the chip's limit is ~10 ms).
  The watchdog never fired in these runs. In a forced test it brought the chip back in ~0.6 s.
- **3 RT priority:** it's what makes 4 pay off, and it also tightened GPS and LiDAR. YOLO wasn't affected (same FPS).
  The scheduler probe runs at normal priority, so it still shows ~2.7 ms p99: that's what *normal* threads get while
  YOLO saturates the cores. Fixing that is suggestions 1 and 2.

## Things found along the way

- The BNO085 occasionally sends command-channel packets mid-stream (5 in one run). The stock Adafruit parser raised
  `Unprocessable Batch bytes` on them, which would have crashed `imu.py`. `PiBNO08X_SPI._handle_packet` now skips
  channels 0/1, as the library already does in its own wait loop.
- The first RT run showed a 467 ms scheduler stall. It was the benchmark, not the robot: workers serialised their samples
  at RT priority during shutdown. Fixed: probes stop first, and workers drop to normal priority before dumping.

## Where the code changed (nothing committed)

- `pwm-lab5/src/main.c`: USART5 RX on circular DMA (DMA1 ch1), TX on double-buffered DMA (ch2). An interrupt was ruled out
  because `autotest.o` already defines `USART3_8_IRQHandler`. Telemetry lines end with ` ORE=n` if an overrun ever happens.
- `testing/imu.py`: `GpiodInt` (libgpiod edge events on GPIO25), `Watchdog` + `recover_imu()`, `--rt`, command-channel skip.
- `testing/lidar.py`: UART2 / `/dev/ttyAMA2` default, VMIN block reads, `plausible()` packet checks, `rejected` counter.
  (`lidar_viz.py` defaults to `/dev/ttyAMA2` too.)
- `testing/rt_tune.py`: RT priority, timer slack, affinity and mlockall helpers for any app.
- Root (via `bench/setup_root_tuning.sh`): `dtoverlay=uart2-pi5`, udev FTDI latency rule, rtprio/memlock limits for sdteam22.

## Next

YOLO is now the bottleneck: ~1.8 cores, 0.8–1 s from capture to detection, and it slows every normal-priority thread.
Suggestion 1 (newest-frame capture, NCNN / 320 px, 2 threads) and 2 (cores 2-3 for YOLO, sensors + IRQs on core 1) are next.
