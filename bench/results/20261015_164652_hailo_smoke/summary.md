# Benchmark 20261015_164652_hailo_smoke

Measured window: 20 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 6476 | 0.03 | 0.10 | 0.23 | 0.29 | 0.34 | 10 | 0 (0.00%) |
| imu | service_ms | 6476 | 0.35 | 0.62 | 1.15 | 1.37 | 1.68 | - |  |
| imu | period_ms | 1998 | 10.04 | 10.72 | 11.68 | 12.77 | 12.98 | 15 | 0 (0.00%) |
| yolo | grab_ms | 308 | 49.24 | 51.14 | 53.19 | 55.11 | 55.37 | - |  |
| yolo | infer_ms | 308 | 17.12 | 19.20 | 22.41 | 31.54 | 35.00 | - |  |
| yolo | e2e_ms | 308 | 52.41 | 56.79 | 59.45 | 70.85 | 73.49 | 500 | 0 (0.00%) |
| yolo | age_ms | 308 | 34.37 | 38.27 | 40.34 | 40.96 | 41.15 | - |  |
| yolo | loop_ms | 308 | 66.81 | 69.68 | 73.80 | 83.62 | 86.23 | - |  |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.90 |
| YOLO frames/s | 15.40 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 132.3 | 52 | 2627 | 5018 | 6010 | 5.06% | 2.868% |
| cpu1 | 68.4 | 54 | 421 | 890 | 1497 | 6.93% | 0.049% |
| cpu2 | 148.8 | 52 | 2177 | 4994 | 7041 | 7.94% | 3.967% |
| cpu3 | 147.9 | 52 | 2125 | 4997 | 6040 | 8.16% | 3.940% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 9.1 | 0.0 | 1021.4 | 4 | 1 |
| yolo | 9.0 | 56.8 | 280.4 | 17 | 2,3 |
| jitter | 1.6 | 12.4 | 3953.5 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.4 | 8.2 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 14.28 | 4.08 | 29.41 |
| cpu1_util_pct | 9.97 | 2.17 | 15.38 |
| cpu2_util_pct | 17.84 | 10.00 | 36.73 |
| cpu3_util_pct | 16.27 | 4.26 | 36.73 |
| ext5v_v | 4.91 | 4.85 | 4.94 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 47.26 | 45.75 | 48.50 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.39 | 1.08 | 2.52 |
