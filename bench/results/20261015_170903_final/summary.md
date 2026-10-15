# Benchmark 20261015_170903_final

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38855 | 0.03 | 0.08 | 0.18 | 0.28 | 0.57 | 10 | 0 (0.00%) |
| imu | service_ms | 38858 | 0.40 | 0.54 | 0.86 | 1.31 | 2.30 | - |  |
| imu | period_ms | 11992 | 10.04 | 10.57 | 11.43 | 12.04 | 13.05 | 15 | 0 (0.00%) |
| gps | line_gap_ms | 4205 | 1.44 | 190.50 | 193.16 | 194.56 | 194.78 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 200.19 | 202.96 | 203.76 | 204.19 | - |  |
| gps | gga_jitter_ms | 600 | 0.05 | 2.73 | 3.11 | 4.21 | 4.25 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1192 | 100.58 | 101.30 | 101.74 | 102.59 | 102.73 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215979 | 0.97 | 1.45 | 1.75 | 2.15 | 11.36 | 10 | 4 (0.00%) |
| yolo | grab_ms | 3600 | 14.96 | 18.96 | 19.04 | 19.87 | 20.66 | - |  |
| yolo | infer_ms | 3601 | 17.07 | 17.15 | 17.68 | 20.89 | 25.76 | - |  |
| yolo | e2e_ms | 3601 | 51.32 | 55.31 | 55.44 | 59.06 | 64.05 | 500 | 0 (0.00%) |
| yolo | age_ms | 3600 | 34.23 | 38.21 | 38.27 | 39.38 | 40.71 | - |  |
| yolo | loop_ms | 3601 | 32.04 | 36.05 | 36.20 | 38.91 | 44.13 | - |  |
| cell | poll_late_ms | 120 | 0.02 | 0.03 | 0.06 | 0.36 | 0.40 | - |  |
| cell | poll_rtt_ms | 120 | 101.17 | 101.29 | 102.53 | 102.93 | 102.97 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 104.06 | 105.52 | 108.52 | 108.82 | 108.86 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.62 | 2.99 | 5.71 | 6.87 | 6.91 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.80 | 99.86 | 100.18 | 100.72 | 100.74 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| GPS NMEA lines/s | 35.04 |
| LiDAR packets/s | 1799.82 |
| YOLO frames/s | 30.01 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.93 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| imu | bad_headers | 0 |
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 56.2 | 52 | 90 | 993 | 5377 | 0.72% | 0.094% |
| cpu1 | 86.5 | 55 | 497 | 1548 | 12820 | 16.25% | 0.280% |
| cpu2 | 137.1 | 52 | 1902 | 2364 | 6018 | 9.85% | 3.905% |
| cpu3 | 139.7 | 52 | 1876 | 2269 | 5797 | 10.13% | 4.017% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 8.8 | 0.1 | 1020.4 | 4 | 1 |
| gps | 0.8 | 58.0 | 69.1 | 2 | 1 |
| lidar | 6.7 | 120.3 | 5204.0 | 1 | 1 |
| yolo | 16.3 | 75.7 | 545.1 | 17 | 2,3 |
| cell | 0.1 | 0.0 | 17.5 | 1 | 0 |
| motor | 1.0 | 16.7 | 137.3 | 2 | 1 |
| jitter | 1.6 | 33.4 | 3998.4 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.3 | 8.2 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 2.90 | 0.00 | 57.14 |
| cpu1_util_pct | 21.33 | 8.82 | 46.51 |
| cpu2_util_pct | 12.47 | 0.00 | 38.46 |
| cpu3_util_pct | 13.79 | 0.00 | 44.00 |
| ext5v_v | 4.90 | 4.80 | 4.95 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 48.48 | 46.30 | 50.15 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.82 | 1.21 | 3.71 |
