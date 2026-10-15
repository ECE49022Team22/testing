# Round 3: AI HAT+ (Hailo-8L), and the whole progression

All runs: every app at once (IMU, GPS, LiDAR, camera + stop-sign detection, Notecard, STM32 motor link), 120 s
unless noted, plus two 10-minute soaks. New since round 2: everything rewired (pinout in the session notes), the
AI HAT+ fitted, and `setup_root_cores.sh` applied (`isolcpus=1`, sensor IRQs on core 1, performance governor).

| stage | run | what it is |
|---|---|---|
| Baseline | `20261008_160357_baseline` | apps as written, nothing tuned |
| Round 1 | `20261008_165047_tuned2` | RT priorities, IMU edge INT + watchdog, LiDAR on UART2, motor DMA + 1 ms FTDI timer |
| Round 2 (pre-HAT best) | `20261008_173246_cores` | + YOLO on NCNN 640 (CPU), newest frame, core split |
| Today, CPU YOLO | `20261015_164910_cores_iso` | round 2 on today's system: isolated core 1, fixed 2-thread NCNN, camera fix |
| AI HAT | `20261015_165124_hailo` | YOLO on the Hailo-8L (yolov8s, conf 0.6) |
| **Final** | `20261015_170903_final` | AI HAT + sensor RT priorities moved below 50 (see "priority inversion") |
| **Final soak** | `20261015_171114_final_soak` | the same for 10 minutes |

Config for the final system: `final.toml`.

## Verdict

**The system now meets every timing target we can measure, with a lot of CPU headroom.** One thing still blocks
the stop-sign function on a real course: the pretrained model calls "no entry" signs stop signs.

- All four sensor streams run at full rate, with no late IMU samples and nothing lost (0 LiDAR CRC errors, 0 motor timeouts, 0 IMU stalls
  in 12 minutes of final runs).
- Stop-sign capture → detection: **51 ms p50 / 55 ms p99 at 30 fps**, against 225 / 311 ms at 6.5 fps before the HAT
  and 872 / 1017 ms at 2.2 fps at the start. Detection range is also slightly better.
- The CPU is mostly idle (cores 3 / 22 / 12 / 13 %). Before the HAT, cores 2–3 were at 81–90%, and CPU YOLO drove the 3 A supply into
  **under-voltage and CPU throttling** (`get_throttled` = 0x50005 live during `20261008_173031_yolo`). With the HAT:
  no under-voltage, 50 °C max.
- **Blocking issue:** the pretrained COCO model (on CPU or Hailo) flags red look-alike signs. The Hailo yolov8s calls 57% of
  "no entry" discs a stop sign even at confidence ≥ 0.5. Fix: the team's fine-tuning pipeline (it already has a `do_not_enter` class),
  compiled for Hailo. See the plan below.

## Side by side: pre-HAT vs AI HAT (p50 / p99 / max)

| | Baseline | Round 1 | Round 2: pre-HAT best | Today, CPU YOLO | AI HAT | **Final** | **Final, 10 min** |
|---|---|---|---|---|---|---|---|
| **Stop sign: capture → detection** | 872 / 1017 / 1062 ms | 826 / 950 / 1046 | 225 / 311 / 380 | 167 / 254 / 326 | 51 / 56 / 65 | **51 / 55 / 64** | **51 / 55 / 64** |
| YOLO inference | 437 / 564 ms | 418 / 495 | 150 / 193 | 100 / 160 | 17 / 17 | **17 / 18** | 17 / 17 |
| YOLO frames/s | 2.2 | 2.4 | 6.5 | 9.6 | 30.0 | **30.0** | 30.0 |
| IMU sample period (10 ms) | 10.0 / 17.6 / 29.8 | 10.0 / 12.2 / 14.3 | 10.0 / 12.5 / 15.2 | 10.0 / 14.5 / 31.9 | 10.0 / 11.3 / 12.4 | **10.0 / 11.4 / 13.1** | 10.0 / 11.3 / 35.7¹ |
| IMU samples > 15 ms late | 2.6% | 0% | 0.01% | 0.68% | 0% | **0%** | 0% |
| IMU INT → serviced | ≤0.6 / ≤3.3 / ≤8.5² | 0.10 / 0.39 / 0.92 | 0.14 / 0.36 / 0.60 | 0.18 / 1.44 / 13.8³ | 0.03 / 0.22 / 1.21 | **0.03 / 0.18 / 0.57** | 0.03 / 0.17 / 0.47 |
| GPS timing error (5 Hz) | 0.33 / 3.7 / 21.2 | 0.14 / 3.1 / 5.2 | 0.50 / 6.1 / 8.3 | 0.52 / 9.5 / 16.7 | 0.05 / 3.0 / 3.1 | **0.05 / 3.1 / 4.3** | 0.07 / 3.0 / 4.1 |
| LiDAR delivery above best case | 0.79 / 3.7 / 11.2 | 1.15 / 3.6 / 8.0 | 1.08 / 3.2 / 9.9 | 1.13 / 3.7 / 8.7 | 1.34 / 2.3 / 6.0 | **0.97 / 1.8 / 11.4** | 1.01 / 1.8 / 24.5¹ |
| LiDAR CRC errors | 4,292 | 0 | 0 | 0 | 0 | **0** | 0 |
| Motor command → reply | 11.3 / 27.2 / 31.0 | 2.8 / 6.4 / 10.5 | 2.9 / 6.3 / 8.4 | 3.0 / 6.5 / 8.6 | 2.6 / 5.8 / 6.9 | **2.6 / 5.7 / 6.9** | 2.6 / 5.8 / 7.2 |
| Motor commands not answered | 20 | 0 | 0 | 1 | 0 | **0** | 0 |
| Core load 0/1/2/3 (mean) | 88/64/65/71% | 81/61/67/64 | 53/55/81/81 | 18/65/90/88 | 3/21/12/13 | **3/21/12/14** | 3/22/12/13 |
| CPU used by the apps | 230% | 219% | 153% | 225% | 33% | **34%** | 34% |
| Peak core current / min 5 V | 5.2 A / 4.80 V | 5.2 / 4.80 | 6.5 / 4.76⁴ | 6.4 / 4.77 | 3.8 / 4.83 | **3.7 / 4.80** | 3.5 / 4.80 |
| Max SoC temperature | 60 °C | 59 | 60 | 60 | 53 | **50** | 50 |

¹ One event per 10-minute soak, at ~312 s both times; see "Periodic BNO085 event" below.
² The baseline polled INT, so it only had an upper bound.
³ Priority inversion with the IRQ thread on the isolated core; fixed in Final.
⁴ Under-voltage and throttling flagged during the CPU-YOLO stage (0x50005 live in `20261008_173031_yolo`).

## Stop-sign detection: speed and accuracy

From `results/yolo_accuracy_hailo/` (the team's `evaluate.py` on 197 real photos and 1,180 synthetic images; same test as round 2):

| model | where | time/frame | real signs found | false alarms (real) | smallest reliable sign | 40 px sign, occluded | "no entry" disc called stop (conf ≥ 0.5) |
|---|---|---|---|---|---|---|---|
| YOLO26n 640 | CPU, PyTorch (baseline) | 300 ms | 99% | 1% | 28 px | 32% | 38% |
| YOLO26n 640 | CPU, NCNN (round 2) | 113 ms | 99% | 2% | 28 px | 38% | — (90% at default) |
| **YOLOv8s** | **Hailo-8L** | **17 ms** | **99%** | 8% at 0.25, **1% at 0.6** | **24 px** | **75%** | **57%** |

Hailo's YOLOv8s is a bigger model than YOLO26n, and it shows: it detects smaller and occluded signs better. It's also more confident on
red look-alikes. The benchmark runs it at conf 0.6 (98% found, 1% false alarms on real photos).

What that means on the robot (camera 640 px, 70° FOV; "confirm" = 3 consecutive detections, as `stop_sign_detector.py` requires):

| | Baseline | Round 2 (CPU) | Today, CPU | **Final (Hailo)** |
|---|---|---|---|---|
| detected out to: 12" sign / 30" road sign | 5.0 m / 12.4 m | 5.0 / 12.4 | 5.0 / 12.4 | **5.8 m / 14.5 m** |
| first detection → confirmed (p99) | ~1.9 s | ~0.62 s | ~0.46 s | **~0.12 s** |
| distance driven while confirming at 1 m/s / 3 m/s | 1.9 m / 5.8 m | 0.6 / 1.8 m | 0.46 / 1.4 m | **0.12 m / 0.37 m** |

## Does it work for the project?

The team docs don't state latency targets, so these are the ones the benchmark has used since round 1, derived from each device.
Change them if the robot needs something else.

| requirement (assumed) | final result | |
|---|---|---|
| IMU: 100 Hz, no gap > 15 ms, INT serviced < 10 ms (the chip stops signalling after ~10 ms) | 99.9 Hz; max gap 13 ms (35.7 ms once per 10 min); INT max 0.57 ms | ✅ |
| LiDAR: every 10 Hz scan, delivered < 10 ms after its best case | 9.94 scans/s, p99 1.8 ms (24.5 ms once per 10 min), 0 CRC errors | ✅ |
| GPS: 5 Hz fixes within 20 ms of their grid | max 4.3 ms | ✅ (PPS untested: needs a fix outdoors) |
| Motor link: command acknowledged < 20 ms, nothing lost | p99 5.7 ms, max 7.2 ms, 0 of ~12,000 lost | ✅ |
| Stop sign: confirmed well before reaching it | confirmed in ~0.12 s; seen from 5.8 m (12" sign) | ✅ |
| Stop sign: don't stop for other red signs | 57% of "no entry" discs flagged | ❌ needs the fine-tuned model |
| Cellular: Notecard requests don't stall the robot | ~103 ms each, on core 0, away from the sensors | ✅ |
| No throttling / under-voltage / overheating over 10 minutes | none; 50 °C; 5 V ≥ 4.80 V | ✅ (but see power) |

Not covered: the motor was commanded to 0 RPM (no motor current), GPS had no fix (indoors), and the Notecard radio was mostly idle.
A driving test with the motor loaded is the next check, especially for power.

## Problems found and fixed in this round

1. **Camera ran at half rate.** `CAP_PROP_BUFFERSIZE=1` (copied from `stop_sign_detector.py`) leaves the UVC driver no buffer
   for the next frame, so it drops every other one: 16 fps instead of 30. Frames weren't any fresher for it (34 ms old either way).
   `latest_camera.py` now uses 2 buffers. **`stop_sign_detector.py` still has 1** and is capped at ~15 fps.
2. **Priority inversion after core isolation.** The kernel thread that delivers the IMU's INT edge (`irq/NN-bno085-int`)
   runs at SCHED_FIFO 50. Once `setup_root_cores.sh` put sensor IRQs on core 1, it sat below the LiDAR (60), motor (70) and IMU (80)
   processes it serves. INT waits reached 14 ms (`cores_iso`). Fix: the apps go below 50 (IMU 49 > motor 48 > LiDAR 47 > GPS 46,
   `final.toml`). The `imu.py --rt` help now says so.
3. **Corrupted SPI header → 0.9 s IMU outage.** In the first soak, one packet header claimed ~32 KB. Reading it held the SPI bus
   for 292 ms (normal: < 1 ms), then the watchdog reset the chip. `imu.py` now drops any header claiming more than 1 KB
   (`bad_headers` counter). The second soak caught one, and it cost 24 ms instead of 0.9 s, with no reset.
4. **HailoRT crashes on teardown and on import order.** `hailo_platform` segfaults if it's imported after torch/matplotlib, or if
   its objects are garbage-collected. `hailo_detector.py` / `w_yolo.py` / `tools/eval_hailo.py` import it first and close it
   explicitly.
5. **AI HAT+ ID EEPROM isn't read.** The PCIe port is forced on with `dtparam=pciex1` / `pciex1_gen=3` (`setup_root_hailo.sh`). The link
   runs at Gen 3 ×1, 8 GT/s.

## Still open, and the plan

In order of importance for the project:

1. **Stop-sign false alarms on look-alikes (blocking).** Run the team's fine-tuning pipeline (`stop-sign-eval/train/`,
   classes `stop_sign` + `do_not_enter`), then compile the result for Hailo-8L with Hailo's Dataflow Compiler. That needs an x86 Linux
   PC with Hailo's DFC; the Hailo Model Zoo has a YOLOv8 retraining/compile flow. Score it with `tools/eval_hailo.py` on the
   "hard negatives" set. Until then: conf ≥ 0.6, 3-frame confirmation, and treat detections as advisory.
2. **Power supply.** The PSU still negotiates 3 A (USB capped at 600 mA total) and 5 V dips to 4.80 V. CPU YOLO already caused
   under-voltage + throttling, and a running motor, the cellular radio and the HAT all add load. Use the 5 V/5 A supply, then rerun
   `final.toml` with the motor actually turning (`--rpm 0 5`).
3. **Periodic BNO085 event (~every 5 min).** Both soaks had their only disturbance ~312 s in, starting with a bad SPI header from
   the IMU. It looks internal to the chip, possibly its periodic dynamic-calibration save, but that isn't confirmed. Next: log the raw header
   when `bad_headers` increments, run a 1-hour soak to get the period, and test whether turning off the chip's periodic calibration save removes it.
   Also try shorter SPI wires: the stacking header lengthened them.
4. **Raise the kernel IRQ threads instead (optional).** A root boot service could `chrt` the sensor IRQ threads (`irq/*-bno085-int`,
   SPI, UARTs) above the apps, so the apps aren't limited to < 50. Not needed for the current numbers.
5. **Hailo driver warning.** HailoRT 4.23's driver triggers a kernel `WARNING` (`find_vma` without the mmap lock) every time a
   model is loaded on kernel 6.18. It's harmless so far, but it taints the kernel. Watch for a HailoRT update (`apt upgrade hailo-all`) or report it to Hailo.
6. **Camera is now the biggest share of detection latency** (34 of 51 ms). Tested 60 fps (`20261015_170412_hailo60`): p50
   49 ms but a worse p99 (70 ms), and more load on the IMU's core. Not worth it. A fixed short exposure would help motion blur more than latency.
7. **Fix `stop_sign_detector.py`** (BUFFERSIZE 2, or use `latest_camera.py`) if the rules-based detector stays in use.
8. **Longer and outdoor tests:** a 1-hour soak, GPS PPS with a fix, and a driving test.

## Reproduce

    cd ~/testing/bench
    python3 run_bench.py -c final.toml                          # 120 s, everything at once
    python3 run_bench.py -c final.toml --duration 600 --label final_soak
    python3 compare.py results/20261008_160357_baseline results/20261008_173246_cores results/<new>
    cd ~/stop-sign-eval && .venv/bin/python ~/testing/bench/tools/eval_hailo.py    # accuracy incl. Hailo
