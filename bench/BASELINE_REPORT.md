# Baseline: all robot apps running at once on the Pi 5

Run 2026-10-08, after updating the bootloader EEPROM to 2026-09-10 (`latest` channel). Stock settings: `ondemand` governor,
no pinning, default priorities, desktop session running, 3 A PSU. Raw data:
`results/20261008_160357_baseline` (120 s, all apps together), `results/20261008_160734_baseline_solo` (30 s, each app
alone), `results/20261008_161145_imu_solo_retry1` (IMU alone, used below because the first solo IMU run stalled).

## Results

| What | Alone p50 / p99 / max | All together p50 / p99 / max | Deadline misses together |
|---|---|---|---|
| IMU sample period (should be 10 ms) | 10.0 / 12.0 / 20.7 ms | 10.0 / **17.6 / 29.8 ms** | 2.6% of samples > 15 ms |
| IMU INT wait (chip gives up at ~10 ms) | 0.6 / 0.6 / 1.8 ms | 0.6 / 3.3 / **8.5 ms** | none yet, but max is close to 10 |
| GPS GGA timing error (5 Hz grid) | 0.0 / 2.9 / 2.9 ms | 0.3 / 3.7 / **21.2 ms** | 1 of 600 > 20 ms |
| LiDAR delivery latency above best case | 0.6 / 1.1 / 7.4 ms | 0.8 / **3.7 / 11.2 ms** | 3 packets > 10 ms |
| LiDAR CRC errors | 303 in 30 s (0.6% of packets) | **4,292 in ~130 s (1.9%)** | 18 corrupted packets passed the CRC |
| YOLO inference | 331 / 383 / 397 ms | **437 / 564 / 657 ms** | |
| YOLO capture → detection | 653 / 721 / 745 ms | **872 / 1017 / 1062 ms** | 2.2 FPS (3.0 alone) |
| Motor command → "OK" | 11.1 / 28.1 / 30.9 ms | 11.3 / 27.2 / 31.0 ms | 4.8% > 20 ms; 0.9% never answered |
| Notecard request (I2C) | 101.5 / 102.6 / 102.7 ms | 103.3 / 107.5 / 109.8 ms | |

System while everything ran: 72% average CPU across the 4 cores (core 0 at 88%), clock stayed at 2.4 GHz, 60 °C max,
no throttling, core rail up to 5.2 A, 5 V input down to 4.80 V.

| Process | CPU (% of one core) | Involuntary context switches/s |
|---|---:|---:|
| YOLO | 179 | 9,107 |
| LiDAR | 30 | 1,091 |
| IMU | 18 | 3,321 |
| GPS, motor, cell | ~1 each | |

## What the numbers say

1. **YOLO is the problem for everyone else.** It uses ~1.8 cores spread over all four, and it is the reason the
   sensors' tail latency grows 2–7× when everything runs together.
2. **YOLO's own latency is twice its inference time, even when it runs alone.** OpenCV returns a frame that was
   queued during the previous inference, so each frame is already ~one inference old before YOLO starts.
3. **Motor latency doesn't change with load, so the CPU isn't the cause.** Two causes show up: the FTDI adapter's 16 ms latency timer, and
   the firmware dropping command bytes (see suggestion 6). 0.9% of commands never get a reply, even with nothing else running.
4. **The LiDAR loses bytes on the PIO UART, and more of them under load** (0.6% → 1.9% bad packets). About 1 in 256 bad packets
   passes the 8-bit CRC, so garbage points reach the scan.
5. **The IMU stalled once when it was running alone:** the BNO085 stopped raising INT 3.5 s in and never recovered. It didn't happen again in 2 retries.
   `imu.py` has no watchdog, so on the robot the IMU would just go silent.
6. **The scheduler floor is poor even when idle.** The median timer wakeup is 52 µs late. That's exactly the default 50 µs
   timer slack for normal threads. About 2% of wakeups are more than 1 ms late, partly because of how the 1 kHz probe lines up.

## Suggestions, ordered by expected payoff

### 1. Fix YOLO first (biggest effect on everything)
- **Always process the newest frame.** Read the camera in its own thread that keeps only the latest frame (or call
  `cap.grab()` until the queue is empty before `retrieve()`). Expected: capture → detection drops by about one inference time (~50%).
- **Export the model to NCNN** (`yolo export model=yolo26n.pt format=ncnn`), ideally INT8, and/or **run at `imgsz=320`/`416`**.
  NCNN is usually several times faster than PyTorch on a Pi 5 CPU, and 320 px does ~4× less work than 640. Check accuracy
  with `evaluate.py` in `stop-sign-eval`.
- **Limit and pin its threads:** `torch.set_num_threads(2)` (or NCNN threads = 2) plus `cpus = "2,3"`. Ultralytics silently
  sets 3 threads right now.
- **Run detection only as often as needed** (e.g. 5 Hz), or use the rules-based detector as a cheap first pass.
- An accelerator (Raspberry Pi AI HAT+ / Hailo) takes this off the CPU entirely, if the budget allows.

### 2. Split the cores: sensors on one, vision on the others
- Try pinning first (no reboot needed): IMU, LiDAR, motor and GPS on core 1; YOLO on cores 2-3; desktop and
  cellular on core 0. Then make it stronger with kernel arguments in `cmdline.txt`: `isolcpus=1 nohz_full=1 rcu_nocbs=1`.
- **Send the sensors' hardware interrupts to the sensor core:** write to `/proc/irq/<n>/smp_affinity_list` for the SPI, UART0,
  PIO and xhci (USB: FTDI + camera) interrupts. Find them in `/proc/interrupts`.

### 3. Give real-time priority to the code with deadlines
- `rt_prio` in the TOML (SCHED_FIFO, needs root): IMU ~80 (its 10 ms INT deadline), motor ~70, LiDAR ~60, GPS ~50;
  YOLO and cellular stay normal, or get `nice = 10`.
- SCHED_FIFO threads get no timer slack. For anything left as a normal thread, call `prctl(PR_SET_TIMERSLACK, 1)`
  (Python: `ctypes`) to remove the 50 µs slack from every sleep.
- Add `mlockall` (or keep the processes small) so page faults don't add to the tail latency.

### 4. Make the IMU interrupt-driven and self-healing
- Swap the 0.5 ms sleep-poll on INT for **edge events from libgpiod** (`python3-libgpiod` is installed). That cuts ~2,000
  wakeups/s and 3,300 involuntary context switches/s, and the events come with kernel timestamps.
- **Add a watchdog:** if there's no sample for ~100 ms, hard-reset the BNO085 (the reset code is already in `PiBNO08X_SPI.hard_reset`).

### 5. LiDAR: move it to a hardware UART and validate packets
- Move the TX wire to **pin 29 (GPIO5)** with `dtoverlay=uart2-pi5`. A hardware UART has a FIFO and doesn't depend
  on the PIO's interrupt and DMA servicing. Re-measure `crc_errors`.
- Reject packets whose timestamp or angle doesn't fit the previous one, so corrupted packets that pass the CRC are dropped
  (`summarize.py:lidar_offsets` shows how).
- Parsing costs 30% of a core in Python. Read bigger chunks (`ser.read(4096)` with a short timeout, which cuts the 6,250
  wakeups/s) and parse with `numpy.frombuffer`/`struct.iter_unpack`, or in C.

### 6. Motor link: two quick fixes
- **FTDI latency timer 16 → 1 ms**, permanently with a udev rule:
  `ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"`. That's most of the 11 ms round trip.
- **Firmware:** `motor_uart_loop()` checks USART5 in a polling loop and blocks while it prints the 10 Hz telemetry line (~4 ms at 115200).
  A command byte that arrives during that print overruns and is lost (the ORE flag is cleared and the byte dropped). That fits
  the 0.9% of commands with no reply, which happens with or without load. Use an RXNE interrupt with a ring buffer, or circular DMA, and
  send telemetry by DMA or interrupt as well. Raising the baud rate (e.g. 921600) also shortens every frame.
- Longer term: put time-critical control (and possibly the IMU) on the STM32, and have the Pi send setpoints.

### 7. Clocks, power, cooling
- **Lock the clock:** `performance` governor (`cpufreq-set -g performance`, or `scaling_min_freq=2400000`). Under full load
  it already held 2.4 GHz, but `ondemand` ramps down between bursts, which adds wakeup latency when load is light.
- **Power:** the PSU negotiated only **3 A**, so the Pi caps USB at 600 mA total (camera + FTDI on USB), and 5 V
  dropped to 4.80 V with the core drawing 5.2 A. CELLULAR.md already records undervoltage during radio bursts. Use the official 5 V/5 A supply
  (or `usb_max_current_enable=1` only if the supply really can deliver it). Undervoltage throttling would ruin every number here.
- **Cooling:** it hit 60 °C in 2 minutes. Run a 20-minute test in the robot's enclosure; the Pi throttles at 80–85 °C. An active
  cooler keeps the 2.4 GHz clock steady.
- Locking a *lower* frequency (e.g. `arm_freq=2000`) trades a little throughput for less heat and current, and steadier
  timing. Worth comparing with the benchmark.

### 8. Remove background load
- Boot to the console instead of the desktop (`raspi-config` → System → Boot → Console): no labwc, panel, or terminal
  redraws. During these runs the Claude session and its terminal used ~30% of one core.
- Disable services you don't use (`bluetooth`, `cups`, `avahi-daemon`, `ModemManager` if present).
- **Notecard on I2C at 50 kHz** (`i2c_arm_baudrate=50000`) takes ~100 ms per request. It's off the critical path, but
  if 50 kHz was a workaround for the earlier power problems, try 100 kHz once the PSU is fixed.

### 9. Bigger changes, if the above isn't enough
- **PREEMPT_RT kernel** (the Pi kernel can be built with `CONFIG_PREEMPT_RT`): bounds worst-case wakeups to tens of µs.
- **Fewer processes / less Python on the hot path:** a C or Rust sensor hub for IMU + LiDAR + motor, publishing over shared memory.
- **Free-threaded Python is not a fix:** the GIL isn't the bottleneck here; scheduling and I/O are.

## Suggested order of experiments
Change one thing per run and compare with `compare.py results/20261008_160357_baseline results/<new>`:
1. YOLO newest-frame + 2 threads → 2. pinning (`cpus`) → 3. `rt_prio` → 4. performance governor + FTDI latency timer
→ 5. NCNN/320 px → 6. isolcpus + IRQ affinity → 7. LiDAR on UART2, IMU on gpiod edges → 8. console boot / 5 A PSU.
Each run takes 2 minutes. Repeat the important ones 2–3 times: run-to-run variation in the tails (p99.9/max) is real.
