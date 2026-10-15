# Benchmark 20261008_154917_smoke

Measured window: 15 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_wait_ms | 4785 | 0.58 | 0.94 | 3.86 | 5.82 | 7.16 | 10 | 0 (0.00%) |
| imu | service_ms | 4784 | 0.61 | 1.56 | 3.98 | 6.27 | 7.37 | - |  |
| imu | period_ms | 1499 | 10.02 | 12.27 | 15.73 | 19.60 | 23.84 | 15 | 22 (1.47%) |
| gps | line_gap_ms | 504 | 1.41 | 191.47 | 194.43 | 197.93 | 198.91 | - |  |
| gps | gga_period_ms | 75 | 200.00 | 202.76 | 205.21 | 205.86 | 205.93 | - |  |
| gps | gga_jitter_ms | 75 | 0.76 | 4.02 | 5.91 | 5.93 | 5.93 | 20 | 0 (0.00%) |
| yolo | grab_ms | 43 | 2.27 | 2.78 | 3.82 | 3.94 | 3.95 | - |  |
| yolo | infer_ms | 44 | 342.05 | 368.82 | 408.78 | 434.67 | 437.54 | - |  |
| yolo | e2e_ms | 44 | 670.09 | 710.77 | 787.35 | 801.38 | 802.94 | 500 | 44 (100.00%) |
| yolo | loop_ms | 44 | 344.67 | 371.90 | 411.10 | 436.97 | 439.84 | - |  |
| motor | cmd_rtt_ms | 260 | 11.58 | 17.75 | 24.89 | 27.56 | 27.64 | 20 | 10 (3.85%) |
| motor | telem_period_ms | 150 | 96.00 | 111.67 | 112.06 | 114.02 | 114.35 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| GPS NMEA lines/s | 33.60 |
| YOLO frames/s | 2.93 |
| motor telemetry lines/s | 10.00 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| motor | timeouts | 4 |
| motor | overruns | 4 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 223.2 | 63 | 2945 | 4988 | 7667 | 19.44% | 6.032% |
| cpu1 | 291.2 | 62 | 3240 | 5071 | 8994 | 22.11% | 8.885% |
| cpu2 | 280.1 | 62 | 3094 | 5033 | 6041 | 21.65% | 8.643% |
| cpu3 | 264.2 | 62 | 3002 | 5005 | 8520 | 21.16% | 8.081% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 19.1 | 2572.2 | 1801.9 | 4 | 0,2,3 |
| gps | 0.9 | 7.3 | 54.3 | 1 | 1 |
| yolo | 200.7 | 1752.9 | 870.9 | 8 | 0,1,2,3 |
| motor | 1.2 | 14.4 | 68.7 | 2 | 0 |
| jitter | 4.7 | 4.2 | 3920.3 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.8 | 5.6 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 73.61 | 50.94 | 100.00 |
| cpu1_util_pct | 59.74 | 42.55 | 96.00 |
| cpu2_util_pct | 65.76 | 44.00 | 96.00 |
| cpu3_util_pct | 64.59 | 44.44 | 92.31 |
| ext5v_v | 4.92 | 4.86 | 4.96 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 52.11 | 50.70 | 54.00 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.16 | 2.15 | 3.81 |
