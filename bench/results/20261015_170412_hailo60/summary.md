# Benchmark 20261015_170412_hailo60

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38576 | 0.07 | 0.26 | 0.82 | 1.93 | 5.10 | 10 | 0 (0.00%) |
| imu | service_ms | 38847 | 0.50 | 1.04 | 1.82 | 2.20 | 4.15 | - |  |
| imu | period_ms | 11992 | 10.03 | 11.24 | 13.21 | 14.69 | 18.31 | 15 | 9 (0.08%) |
| gps | line_gap_ms | 4187 | 1.44 | 190.53 | 194.36 | 196.91 | 199.16 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 201.76 | 204.13 | 205.65 | 206.45 | - |  |
| gps | gga_jitter_ms | 600 | 0.20 | 2.80 | 4.62 | 5.79 | 6.45 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1192 | 100.62 | 101.45 | 103.21 | 104.69 | 105.08 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215979 | 1.02 | 1.61 | 2.99 | 4.77 | 8.31 | 10 | 0 (0.00%) |
| yolo | grab_ms | 6389 | 0.01 | 0.28 | 1.33 | 4.19 | 10.14 | - |  |
| yolo | infer_ms | 6389 | 17.92 | 20.93 | 23.87 | 27.36 | 31.56 | - |  |
| yolo | e2e_ms | 6389 | 49.36 | 60.20 | 70.21 | 76.53 | 90.32 | 500 | 0 (0.00%) |
| yolo | age_ms | 6389 | 30.63 | 41.09 | 50.48 | 56.86 | 68.16 | - |  |
| yolo | loop_ms | 6389 | 18.01 | 21.17 | 24.29 | 27.85 | 32.22 | - |  |
| cell | poll_late_ms | 120 | 0.04 | 0.40 | 2.95 | 3.34 | 3.35 | - |  |
| cell | poll_rtt_ms | 120 | 102.02 | 104.05 | 107.35 | 108.43 | 108.57 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 110.09 | 112.28 | 113.31 | 113.41 | 113.42 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.71 | 3.35 | 5.95 | 7.08 | 7.31 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.76 | 99.98 | 101.97 | 103.53 | 103.71 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| GPS NMEA lines/s | 34.89 |
| LiDAR packets/s | 1799.82 |
| YOLO frames/s | 53.24 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.93 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 144.3 | 53 | 2954 | 5000 | 7253 | 7.31% | 3.357% |
| cpu1 | 215.2 | 63 | 2788 | 7117 | 12182 | 30.05% | 4.537% |
| cpu2 | 255.0 | 54 | 2724 | 4531 | 7999 | 19.11% | 8.886% |
| cpu3 | 257.9 | 54 | 2723 | 4596 | 7822 | 19.36% | 8.998% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 16.7 | 0.0 | 1015.1 | 4 | 1 |
| gps | 1.0 | 61.5 | 61.3 | 2 | 1 |
| lidar | 10.6 | 175.0 | 4553.9 | 1 | 1 |
| yolo | 35.5 | 377.4 | 1155.7 | 18 | 2,3 |
| cell | 0.2 | 0.8 | 17.5 | 1 | 0 |
| motor | 1.4 | 20.4 | 134.8 | 2 | 1 |
| jitter | 2.8 | 57.1 | 3935.8 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 1.2 | 7.9 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 23.74 | 8.33 | 55.81 |
| cpu1_util_pct | 37.17 | 23.53 | 52.83 |
| cpu2_util_pct | 36.30 | 25.00 | 60.00 |
| cpu3_util_pct | 36.11 | 22.73 | 60.42 |
| ext5v_v | 4.86 | 4.76 | 4.92 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 49.82 | 47.40 | 51.80 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 2.35 | 1.14 | 4.14 |
