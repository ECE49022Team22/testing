# Benchmark 20261015_171114_final_soak

Measured window: 600 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 194297 | 0.03 | 0.08 | 0.17 | 0.27 | 0.47 | 10 | 0 (0.00%) |
| imu | service_ms | 194297 | 0.40 | 0.54 | 0.82 | 1.00 | 24.02 | - |  |
| imu | period_ms | 59959 | 10.04 | 10.57 | 11.33 | 11.88 | 35.67 | 15 | 1 (0.00%) |
| gps | line_gap_ms | 21301 | 1.43 | 190.50 | 193.38 | 194.52 | 196.13 | - |  |
| gps | gga_period_ms | 3000 | 200.00 | 200.24 | 202.97 | 203.14 | 204.07 | - |  |
| gps | gga_jitter_ms | 3000 | 0.07 | 2.70 | 3.04 | 3.58 | 4.07 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 5960 | 100.58 | 101.26 | 101.70 | 102.15 | 103.18 | 150 | 0 (0.00%) |
| lidar | excess_ms | 1079892 | 1.01 | 1.50 | 1.80 | 1.97 | 24.52 | 10 | 36 (0.00%) |
| yolo | grab_ms | 18002 | 14.98 | 18.97 | 19.05 | 19.10 | 22.00 | - |  |
| yolo | infer_ms | 18001 | 17.06 | 17.15 | 17.29 | 19.37 | 22.92 | - |  |
| yolo | e2e_ms | 18001 | 51.33 | 55.31 | 55.43 | 56.34 | 64.10 | 500 | 0 (0.00%) |
| yolo | age_ms | 18002 | 34.24 | 38.23 | 38.27 | 38.37 | 41.22 | - |  |
| yolo | loop_ms | 18001 | 32.05 | 36.05 | 36.18 | 36.83 | 41.38 | - |  |
| cell | poll_late_ms | 600 | 0.02 | 0.03 | 0.06 | 0.85 | 0.86 | - |  |
| cell | poll_rtt_ms | 600 | 101.20 | 101.33 | 101.83 | 371.03 | 768.40 | 500 | 1 (0.17%) |
| cell | status_rtt_ms | 40 | 108.63 | 108.82 | 108.89 | 108.89 | 108.89 | - |  |
| motor | cmd_rtt_ms | 12000 | 2.61 | 3.00 | 5.78 | 6.82 | 7.20 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 6021 | 99.80 | 99.86 | 100.09 | 100.78 | 100.94 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| GPS NMEA lines/s | 35.50 |
| LiDAR packets/s | 1799.82 |
| YOLO frames/s | 30.00 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.93 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| imu | bad_headers | 1 |
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 54.8 | 52 | 88 | 471 | 6049 | 0.54% | 0.046% |
| cpu1 | 83.5 | 55 | 452 | 1111 | 24808 | 16.24% | 0.142% |
| cpu2 | 136.4 | 52 | 1879 | 2304 | 5959 | 9.80% | 3.883% |
| cpu3 | 140.6 | 52 | 1876 | 2250 | 6933 | 10.29% | 4.155% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 8.7 | 0.1 | 1020.6 | 4 | 1 |
| gps | 0.8 | 55.3 | 71.2 | 2 | 1 |
| lidar | 6.6 | 118.8 | 5216.1 | 1 | 1 |
| yolo | 16.3 | 68.1 | 544.8 | 17 | 2,3 |
| cell | 0.1 | 0.0 | 17.5 | 1 | 0 |
| motor | 1.0 | 17.0 | 137.5 | 2 | 1 |
| jitter | 1.6 | 31.6 | 3999.0 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.3 | 8.5 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 2.51 | 0.00 | 51.04 |
| cpu1_util_pct | 21.86 | 6.06 | 35.56 |
| cpu2_util_pct | 12.48 | 0.00 | 34.04 |
| cpu3_util_pct | 13.29 | 0.00 | 35.38 |
| ext5v_v | 4.90 | 4.80 | 4.94 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 47.78 | 45.75 | 49.60 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.77 | 1.18 | 3.50 |
