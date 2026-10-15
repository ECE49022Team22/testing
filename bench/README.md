# Concurrent latency benchmark

Runs every robot app at once on the Pi 5, each in its own process, and measures latency.

| worker | device | what it measures |
|---|---|---|
| `w_imu.py` | BNO085, SPI0 (pins 16-24) | sample period vs 10 ms, INT wait (BNO085 gives up at ~10 ms), SPI service time |
| `w_gps.py` | UM982, UART0 `/dev/ttyAMA0` (pins 8/10), PPS pin 12 | GGA timing error vs the 5 Hz grid, PPS -> GGA (needs a fix) |
| `w_lidar.py` | STL-27L, UART2 `/dev/ttyAMA2` (RX pin 29) | delivery latency above best case (from the LiDAR's own timestamps), scan period |
| `w_yolo.py` | USB camera + yolo26n (`~/stop-sign-eval`) | capture -> detection (V4L2 timestamp), inference time, FPS |
| `w_cell.py` | Notecard, I2C (pins 3/5) | request round trip |
| `w_motor.py` | STM32 over FTDI `/dev/ttyUSB0` | command -> "OK" round trip, telemetry period. Sends 0 RPM by default |
| `jitter` (C) | — | timer wakeup lateness on each core (a minimal cyclictest) |
| `w_sysmon.py` | — | per-core load, clock, temperature, throttling, PMIC core current / 5 V |

## Use

```bash
sudo ./setup_root.sh && sudo reboot      # once: EEPROM, overlays, PPS permissions
gcc -O2 -pthread -o jitter jitter.c      # once
python3 run_bench.py                     # baseline.toml, all apps concurrently, 120 s
python3 run_bench.py --solo --duration 30   # each app alone (uncontended reference)
python3 run_bench.py -c pinned.toml      # an experiment: copy baseline.toml, change knobs
python3 compare.py results/<baseline> results/<experiment>
```

Configs, in the order they were tried (each adds to the previous one):

| config | adds |
|---|---|
| `baseline.toml` | nothing: apps as they ran originally (the LiDAR now on UART2) |
| `tuned.toml` | SCHED_FIFO for IMU/motor/LiDAR/GPS, timer slack 1 ns, mlockall (suggestion 3) |
| `yolo.toml` | YOLO on NCNN 640 px, newest frame, 2 threads, passive OpenMP waits (suggestion 1) |
| `cores.toml` | sensors pinned to core 1, YOLO to 2-3, rest to 0 (suggestion 2; with `setup_root_cores.sh` for isolation) |

Reports: `BASELINE_REPORT.md` (first measurement + all suggestions), `ROUND1_RESULTS.md` (3, 4, 5, 6),
`ROUND2_RESULTS.md` (1, 2). Root setup scripts: `setup_root.sh` (EEPROM, PPS), `setup_root_tuning.sh`
(UART2, FTDI latency, RT limits), `setup_root_cores.sh` (isolcpus, IRQ affinity, performance governor).
Raw samples are stored as `<worker>.json.gz`; `summarize.py` reads them directly.

Per-worker knobs in the TOML: `cpus` (taskset), `nice`, `rt_prio` (SCHED_FIFO), `env`, `pre`/`post`
commands. `rt_prio` works without sudo once `setup_root_tuning.sh` has installed the rtprio limit
(check `ulimit -r` = 90); negative `nice` still needs root.

The cellular worker pauses the cron-started `receive_demo.py` (`cellular_logger.sh stop`) for the run
and restarts it afterwards, since two processes can't share the Notecard.

Each run writes `results/<time>_<label>/`: raw samples per worker, `logs/`, `env.json`
(clock/governor/config.txt/overlays at run time), `summary.md` and `summary.json`.
The deadline budgets in `summarize.py` are starting points; adjust them to the robot's real needs.
