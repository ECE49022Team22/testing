# Code changes in other repos, used by the benchmark

These two changes live in other team repos but were part of the benchmark rounds, so they're kept here
too: each as the full file and as a patch against the commit it was made on.

## `pwm-lab5/` — STM32 motor firmware (round 1, suggestion 6)

`src/main.c` from [ECE49022Team22/pwm-lab5](https://github.com/ECE49022Team22/pwm-lab5), on top of `5c6712c`
("PID closed loop implementation"). USART5 moves from polling RDR/TDR to DMA:

- RX on DMA1 channel 1 in circular mode (128-byte ring): bytes that arrive while the main loop is busy
  printing telemetry are no longer lost. Before, 0.9% of commands never got a reply.
- TX on DMA1 channel 2, double-buffered: `uart5_puts()` queues and returns instead of busy-waiting ~4 ms
  per telemetry line.
- Not interrupts: the course's `autotest.o` already defines `USART3_8_IRQHandler` (shared by USART3-8).
- Telemetry lines end with ` ORE=n` if an overrun is ever counted.

Apply and flash:

    cd ~/pwm-lab5 && git apply ~/testing/bench/external/pwm-lab5/main.c.patch
    pio run -t upload

Verified: 1,000/1,000 commands answered at 50 Hz; in the benchmarks 0 timeouts over 2,400 commands.

## `stop-sign-eval/` — YOLO detector wrapper (round 2, suggestion 1)

`detectors.py` from [ECE49022Team22/stop-sign-eval](https://github.com/ECE49022Team22/stop-sign-eval), on top of
`0e427fe`. `YoloDetector` is backwards compatible and gains:

- loading exported NCNN models (`*_ncnn_model/` directories) as well as `.pt`;
- `imgsz=None` (new default): use the size an exported model was exported at, else 640;
- `threads=`: inference thread count. For NCNN the net is reloaded with the count set *before* loading,
  because convolution layers fix it at load time (setting it afterwards silently kept 4 threads; see
  ROUND2_RESULTS.md).

Apply, and rebuild the NCNN models (generated files, ~9 MB each, not committed):

    cd ~/stop-sign-eval && git apply ~/testing/bench/external/stop-sign-eval/detectors.py.patch
    for sz in 640 416 320; do
        .venv/bin/yolo export model=yolo26n.pt format=ncnn imgsz=$sz && mv yolo26n_ncnn_model yolo26n_${sz}_ncnn_model
    done

The benchmark (`w_yolo.py`, `yolo.toml`, `cores.toml`) expects them in `~/stop-sign-eval/`.
Run with `OMP_WAIT_POLICY=passive` (the configs set it): NCNN's spinning OpenMP waits slowed it down on 2 cores.
