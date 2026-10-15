# Round 2: suggestions 1 (YOLO) and 2 (core split)

All runs: 120 s, every app running at once, on top of round 1 (`tuned.toml`: RT priorities, IMU edge INT,
LiDAR on UART2, motor DMA + 1 ms FTDI timer). These ran before the core-isolation reboot, so `ondemand`
governor, no `isolcpus`, all IRQs on core 0.

| run | config | what changed |
|---|---|---|
| `20261008_165047_tuned2` | `tuned.toml` | round 1 result (reference) |
| `20261008_173031_yolo` | `yolo.toml` | YOLO: NCNN 640 px, newest frame (`latest_camera.py`), OMP passive waits |
| `20261008_173246_cores` | `cores.toml` | + pinning: sensors on core 1, YOLO on 2-3, cellular/sysmon on 0 |
| `20261008_173459_cores416` | `cores.toml` with the 416 px model | same, NCNN 416 px |

> **Caveat on threads:** these three runs were meant to use 2 NCNN threads, but NCNN fixes the
> convolution thread count when the model loads, and `detectors.py` set it afterwards. So the
> convolutions ran on **4 threads**: spread over all cores in `yolo`, squeezed onto cores 2-3 in `cores` and
> `cores416`. The logs show it (collapsed warning counts in `logs/yolo.log`). Fixed afterwards in
> `stop-sign-eval/detectors.py` by reloading the net with the thread count set first. With the fix, NCNN 640 px
> on cores 2-3 takes **101 ms with 2 threads vs 142 ms with 1** (solo).
> Use the next run, not these, for the final YOLO numbers.

## Results (p50 / p99 / max unless noted)

| | round 1 | + YOLO fixes | + pinning (640) | + pinning (416) |
|---|---|---|---|---|
| YOLO capture → detection | 826 / 950 / 1046 ms | 345 / 450 / 466 ms | **225 / 311 / 380 ms** | 137 / 192 / 243 ms |
| YOLO inference | 418 / 495 / 601 ms | 202 / 260 / 287 ms | 150 / 193 / 275 ms | 72 / 108 / 205 ms |
| frame age when inference starts | ~1 inference (~420 ms) | 142 ms | 72 ms | 65 ms |
| YOLO frames/s | 2.4 | 5.0 | **6.6** | 13.9 |
| IMU sample period | 10.0 / 12.2 / 14.3 ms | 10.1 / 12.6 / 15.6 ms | 10.0 / 12.5 / 15.2 ms | 10.0 / 12.1 / 14.4 ms |
| IMU INT → service | 0.10 / 0.39 / 0.92 ms | 0.14 / 0.47 / 1.19 ms | 0.14 / 0.36 / **0.60 ms** | 0.12 / 0.38 / 0.79 ms |
| GPS GGA timing error | 0.14 / 3.1 / 5.2 ms | 0.13 / 3.2 / 6.0 ms | 0.50 / 6.1 / 8.3 ms | 0.33 / 3.8 / 7.2 ms |
| LiDAR delivery above best case | 1.15 / 3.6 / 8.0 ms | 1.03 / 2.8 / 7.3 ms | 1.08 / 3.2 / 9.9 ms | 1.04 / 2.5 / 6.7 ms |
| Motor command → reply | 2.8 / 6.4 / 10.5 ms | 2.8 / 6.2 / 9.2 ms | 2.9 / 6.3 / 8.4 ms | 2.8 / 6.1 / 7.6 ms |
| Core load, cores 0 / 1 / 2 / 3 (mean %) | 81 / 61 / 67 / 64 | 85 / 64 / 64 / 62 | 53 / 55 / 81 / 81 | 46 / 50 / 77 / 77 |

No IMU stalls, no motor timeouts, no LiDAR CRC errors in any of these runs.

## Model size: speed vs accuracy

From `results/yolo_accuracy_ncnn/` (the team's `evaluate.py`; "smallest reliable" = found in ≥90%):

| model | inference (solo, eval run) | real photos found / false alarms | smallest reliable sign | 30" road sign detected out to |
|---|---|---|---|---|
| PyTorch 640 | 300 ms | 99% / 1% | 28 px | ~12 m |
| **NCNN 640** | 113 ms | **99% / 2%** | **28 px** | **~12 m** |
| NCNN 416 | 52 ms | 96% / 1% | 40 px | ~8.7 m |
| NCNN 320 | 29 ms | 91% / 2% | 48 px | ~7.3 m |

NCNN 640 is the default in `yolo.toml`/`cores.toml`: same accuracy as PyTorch, ~3× faster. 416 px doubles the frame rate
at the cost of ~3 points of recall and ~3 m of range. 320 px loses too much on small/angled/occluded signs.

## Findings

- **Newest-frame capture** removed the stale-frame queue (frame age ~420 ms → 65–140 ms). The age that's left is the camera
  itself (exposure + USB transfer at 30 fps) plus MJPEG decode, and pinning roughly halved it.
- **OpenMP waits:** with the default (spinning) waits, NCNN on 2 cores ran 2× slower than with 1 thread. Part of this was the
  4-thread bug above (4 spinning threads on 2 cores). `OMP_WAIT_POLICY=passive` is set in the configs either way.
- **Pinning** freed core 0 (81 → 46–53%) and made YOLO faster (its threads no longer migrate or compete with the sensors).
  Core 1's normal-priority probe thread now waits behind four RT sensor processes (its p99 goes up), which is intended:
  the sensors themselves stayed within budget, and GPS (lowest RT priority, 50) loosened a little (p99 6 ms vs 3 ms).

## Next

`setup_root_cores.sh` is installed and the Pi has rebooted with `isolcpus=1 irqaffinity=0`, the performance governor
and sensor IRQs on core 1. Still to run: `cores.toml` on that setup with the fixed 2-thread NCNN, compared against
`20261008_173246_cores`.
