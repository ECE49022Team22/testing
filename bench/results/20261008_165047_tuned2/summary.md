# Benchmark 20261008_165047_tuned2

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38812 | 0.10 | 0.22 | 0.39 | 0.65 | 0.92 | 10 | 0 (0.00%) |
| imu | service_ms | 38850 | 0.57 | 0.98 | 1.53 | 2.48 | 5.33 | - |  |
| imu | period_ms | 11990 | 10.04 | 10.98 | 12.18 | 13.23 | 14.26 | 15 | 0 (0.00%) |
| gps | line_gap_ms | 4125 | 1.44 | 190.69 | 193.98 | 194.65 | 194.88 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 200.78 | 202.99 | 204.02 | 205.09 | - |  |
| gps | gga_jitter_ms | 600 | 0.14 | 2.59 | 3.14 | 5.14 | 5.22 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.60 | 101.39 | 103.14 | 106.01 | 107.84 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215986 | 1.15 | 1.79 | 3.64 | 5.62 | 7.99 | 10 | 0 (0.00%) |
| yolo | grab_ms | 283 | 2.37 | 3.28 | 4.27 | 5.60 | 5.81 | - |  |
| yolo | infer_ms | 283 | 418.48 | 467.77 | 495.29 | 576.10 | 601.19 | - |  |
| yolo | e2e_ms | 283 | 826.00 | 898.81 | 949.85 | 1033.93 | 1045.65 | 500 | 283 (100.00%) |
| yolo | loop_ms | 283 | 421.09 | 471.03 | 499.17 | 579.35 | 604.57 | - |  |
| cell | poll_late_ms | 120 | 0.05 | 0.46 | 1.24 | 1.47 | 1.49 | - |  |
| cell | poll_rtt_ms | 120 | 103.00 | 105.42 | 109.35 | 111.10 | 111.33 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 109.50 | 110.84 | 110.88 | 110.88 | 110.88 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.75 | 3.41 | 6.35 | 9.10 | 10.50 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.78 | 100.04 | 101.81 | 103.72 | 104.00 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.92 |
| GPS NMEA lines/s | 34.37 |
| LiDAR packets/s | 1799.88 |
| YOLO frames/s | 2.36 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.94 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 229.0 | 70 | 2696 | 4757 | 7989 | 32.40% | 5.690% |
| cpu1 | 196.7 | 61 | 2250 | 4106 | 7975 | 23.92% | 4.512% |
| cpu2 | 202.9 | 61 | 2345 | 4653 | 8377 | 20.85% | 5.165% |
| cpu3 | 197.2 | 61 | 2275 | 4264 | 7605 | 22.92% | 4.650% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 18.2 | 2.0 | 1019.8 | 4 | 0,2,3 |
| gps | 1.0 | 1.6 | 79.6 | 2 | 0,3 |
| lidar | 15.2 | 8.4 | 5857.4 | 1 | 1 |
| yolo | 182.5 | 4195.5 | 909.3 | 8 | 0,1,2,3 |
| cell | 0.2 | 4.3 | 17.5 | 1 | 2 |
| motor | 1.6 | 0.2 | 158.5 | 2 | 0,3 |
| jitter | 4.7 | 60.9 | 3967.1 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 5.4 | 5.5 | 1 | 2 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 80.96 | 51.28 | 100.00 |
| cpu1_util_pct | 60.93 | 39.13 | 92.45 |
| cpu2_util_pct | 67.33 | 36.36 | 94.55 |
| cpu3_util_pct | 63.64 | 42.55 | 94.12 |
| ext5v_v | 4.89 | 4.80 | 4.95 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 56.16 | 51.25 | 58.95 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.58 | 2.29 | 5.16 |
