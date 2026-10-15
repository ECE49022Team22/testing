# Benchmark 20261015_165339_hailo_soak

Measured window: 600 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 194008 | 0.03 | 0.09 | 0.22 | 0.39 | 10.34 | 10 | 1 (0.00%) |
| imu | service_ms | 194008 | 0.39 | 0.53 | 0.81 | 0.94 | 292.30 | - |  |
| imu | period_ms | 59871 | 10.04 | 10.57 | 11.33 | 11.89 | 915.88 | 15 | 2 (0.00%) |
| gps | line_gap_ms | 21243 | 1.43 | 190.48 | 193.20 | 194.49 | 228.19 | - |  |
| gps | gga_period_ms | 3000 | 200.00 | 200.18 | 202.97 | 203.22 | 240.02 | - |  |
| gps | gga_jitter_ms | 3000 | 0.05 | 2.75 | 3.03 | 3.88 | 40.02 | 20 | 2 (0.07%) |
| lidar | scan_period_ms | 5961 | 100.58 | 101.17 | 101.56 | 102.15 | 119.35 | 150 | 0 (0.00%) |
| lidar | excess_ms | 1079901 | 1.30 | 1.96 | 2.47 | 2.77 | 77.50 | 10 | 225 (0.02%) |
| yolo | grab_ms | 18001 | 14.85 | 18.85 | 18.92 | 18.98 | 23.01 | - |  |
| yolo | infer_ms | 18002 | 17.18 | 17.28 | 17.39 | 18.54 | 28.17 | - |  |
| yolo | e2e_ms | 18002 | 51.46 | 55.44 | 55.56 | 56.18 | 70.56 | 500 | 0 (0.00%) |
| yolo | age_ms | 18001 | 34.24 | 38.22 | 38.26 | 38.34 | 42.38 | - |  |
| yolo | loop_ms | 18002 | 32.05 | 36.05 | 36.18 | 36.58 | 51.19 | - |  |
| cell | poll_late_ms | 600 | 0.02 | 0.04 | 0.08 | 0.53 | 0.53 | - |  |
| cell | poll_rtt_ms | 600 | 101.20 | 101.35 | 101.78 | 102.80 | 103.66 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 40 | 108.62 | 108.82 | 109.40 | 109.64 | 109.67 | - |  |
| motor | cmd_rtt_ms | 12000 | 2.61 | 2.99 | 5.88 | 6.82 | 26.20 | 20 | 1 (0.01%) |
| motor | telem_period_ms | 6021 | 99.79 | 99.85 | 100.06 | 100.81 | 112.60 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.78 |
| GPS NMEA lines/s | 35.40 |
| LiDAR packets/s | 1799.83 |
| YOLO frames/s | 30.00 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.93 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| imu | stalls | 1 |
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 54.2 | 52 | 86 | 393 | 5995 | 0.52% | 0.026% |
| cpu1 | 81.5 | 55 | 403 | 974 | 99202 | 15.79% | 0.090% |
| cpu2 | 136.2 | 52 | 1827 | 2279 | 5586 | 9.84% | 3.905% |
| cpu3 | 143.3 | 52 | 1875 | 2236 | 5964 | 10.53% | 4.365% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 8.6 | 0.0 | 1019.4 | 4 | 1 |
| gps | 0.8 | 47.7 | 72.0 | 2 | 1 |
| lidar | 6.5 | 73.8 | 5280.0 | 1 | 1 |
| yolo | 16.3 | 68.8 | 545.4 | 19 | 2,3 |
| cell | 0.1 | 0.1 | 17.5 | 1 | 0 |
| motor | 1.0 | 10.2 | 137.4 | 2 | 1 |
| jitter | 1.6 | 32.6 | 3999.4 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.3 | 8.6 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 2.41 | 0.00 | 51.55 |
| cpu1_util_pct | 21.46 | 5.71 | 42.22 |
| cpu2_util_pct | 12.40 | 0.00 | 40.74 |
| cpu3_util_pct | 13.28 | 0.00 | 34.33 |
| ext5v_v | 4.90 | 4.81 | 4.94 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 48.01 | 46.30 | 50.15 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.77 | 1.19 | 4.08 |
