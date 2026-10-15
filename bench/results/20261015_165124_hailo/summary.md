# Benchmark 20261015_165124_hailo

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38862 | 0.03 | 0.09 | 0.22 | 0.38 | 1.21 | 10 | 0 (0.00%) |
| imu | service_ms | 38862 | 0.39 | 0.53 | 0.81 | 0.96 | 2.18 | - |  |
| imu | period_ms | 11992 | 10.04 | 10.57 | 11.32 | 11.87 | 12.44 | 15 | 0 (0.00%) |
| gps | line_gap_ms | 4206 | 1.43 | 190.49 | 193.19 | 194.50 | 194.68 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 200.17 | 202.91 | 203.11 | 203.12 | - |  |
| gps | gga_jitter_ms | 600 | 0.05 | 2.76 | 2.95 | 3.12 | 3.13 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1192 | 100.58 | 100.96 | 101.56 | 101.71 | 101.88 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215981 | 1.34 | 1.89 | 2.28 | 2.46 | 6.03 | 10 | 0 (0.00%) |
| yolo | grab_ms | 3600 | 14.84 | 18.84 | 18.91 | 18.96 | 19.08 | - |  |
| yolo | infer_ms | 3600 | 17.19 | 17.28 | 17.40 | 19.04 | 26.79 | - |  |
| yolo | e2e_ms | 3600 | 51.46 | 55.45 | 55.55 | 56.52 | 64.61 | 500 | 0 (0.00%) |
| yolo | age_ms | 3600 | 34.25 | 38.23 | 38.27 | 38.33 | 38.74 | - |  |
| yolo | loop_ms | 3600 | 32.05 | 36.05 | 36.16 | 36.93 | 41.68 | - |  |
| cell | poll_late_ms | 120 | 0.02 | 0.04 | 0.09 | 0.18 | 0.20 | - |  |
| cell | poll_rtt_ms | 120 | 101.24 | 101.42 | 102.02 | 102.20 | 102.21 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 108.64 | 108.75 | 108.78 | 108.79 | 108.79 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.60 | 2.99 | 5.77 | 6.78 | 6.94 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.79 | 99.86 | 100.09 | 100.79 | 101.37 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| GPS NMEA lines/s | 35.05 |
| LiDAR packets/s | 1799.84 |
| YOLO frames/s | 30.00 |
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
| cpu0 | 54.5 | 52 | 88 | 391 | 5041 | 0.52% | 0.035% |
| cpu1 | 80.9 | 55 | 395 | 919 | 3617 | 15.87% | 0.062% |
| cpu2 | 134.9 | 52 | 1832 | 2283 | 5674 | 9.76% | 3.853% |
| cpu3 | 145.5 | 52 | 1874 | 2243 | 5131 | 10.65% | 4.397% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 8.6 | 0.0 | 1020.6 | 4 | 1 |
| gps | 0.8 | 45.6 | 71.6 | 2 | 1 |
| lidar | 6.5 | 76.0 | 5279.0 | 1 | 1 |
| yolo | 16.3 | 66.9 | 546.1 | 19 | 2,3 |
| cell | 0.1 | 0.1 | 17.5 | 1 | 0 |
| motor | 1.0 | 9.8 | 137.5 | 2 | 1 |
| jitter | 1.5 | 31.1 | 3999.7 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.3 | 9.0 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 3.20 | 0.00 | 51.04 |
| cpu1_util_pct | 21.04 | 6.06 | 34.15 |
| cpu2_util_pct | 11.80 | 0.00 | 42.25 |
| cpu3_util_pct | 13.29 | 0.00 | 36.23 |
| ext5v_v | 4.89 | 4.83 | 4.93 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 50.89 | 48.50 | 53.45 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.91 | 1.22 | 3.76 |
