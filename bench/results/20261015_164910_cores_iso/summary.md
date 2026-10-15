# Benchmark 20261015_164910_cores_iso

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38063 | 0.18 | 0.51 | 1.44 | 4.07 | 13.84 | 10 | 4 (0.01%) |
| imu | service_ms | 38680 | 0.87 | 1.48 | 2.23 | 3.07 | 4.93 | - |  |
| imu | period_ms | 11981 | 9.95 | 11.85 | 14.52 | 19.43 | 31.85 | 15 | 81 (0.68%) |
| gps | line_gap_ms | 4216 | 1.43 | 190.55 | 194.71 | 199.52 | 205.04 | - |  |
| gps | gga_period_ms | 600 | 199.99 | 202.00 | 207.97 | 213.57 | 216.70 | - |  |
| gps | gga_jitter_ms | 600 | 0.52 | 3.24 | 9.54 | 15.44 | 16.70 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.63 | 101.62 | 103.66 | 105.21 | 106.51 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215977 | 1.13 | 1.93 | 3.71 | 5.53 | 8.67 | 10 | 0 (0.00%) |
| yolo | grab_ms | 1148 | 0.01 | 0.01 | 0.02 | 0.03 | 0.03 | - |  |
| yolo | infer_ms | 1148 | 99.95 | 117.56 | 159.56 | 191.96 | 205.92 | - |  |
| yolo | e2e_ms | 1148 | 166.84 | 195.58 | 253.57 | 314.90 | 326.30 | 500 | 0 (0.00%) |
| yolo | age_ms | 1148 | 65.95 | 86.48 | 113.41 | 144.97 | 156.85 | - |  |
| yolo | loop_ms | 1148 | 99.96 | 117.57 | 159.58 | 191.98 | 205.94 | - |  |
| cell | poll_late_ms | 120 | 0.05 | 0.10 | 0.74 | 1.10 | 1.13 | - |  |
| cell | poll_rtt_ms | 120 | 102.18 | 103.49 | 107.47 | 109.79 | 110.08 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 109.52 | 111.37 | 112.14 | 112.22 | 112.23 | - |  |
| motor | telem_period_ms | 1204 | 99.71 | 100.19 | 101.71 | 102.87 | 103.14 | 150 | 0 (0.00%) |
| motor | cmd_rtt_ms | 2400 | 2.96 | 4.12 | 6.51 | 7.52 | 8.55 | 20 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.84 |
| GPS NMEA lines/s | 35.13 |
| LiDAR packets/s | 1799.81 |
| YOLO frames/s | 9.57 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.94 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |
| motor | err_replies | 1 |
| motor | timeouts | 1 |
| motor | overruns | 1 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 84.2 | 57 | 697 | 3084 | 6947 | 6.66% | 0.765% |
| cpu1 | 572.8 | 127 | 5302 | 11222 | 33077 | 56.34% | 17.677% |
| cpu2 | 175.4 | 61 | 2427 | 4529 | 7415 | 13.80% | 4.126% |
| cpu3 | 189.3 | 61 | 2540 | 4614 | 6609 | 15.29% | 4.698% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 31.8 | 0.0 | 998.7 | 4 | 1 |
| gps | 1.3 | 84.0 | 44.3 | 2 | 1 |
| lidar | 19.1 | 375.3 | 3213.6 | 1 | 1 |
| yolo | 170.0 | 2052.9 | 8507.8 | 8 | 2,3 |
| cell | 0.2 | 2.2 | 17.5 | 1 | 0 |
| motor | 2.3 | 43.8 | 129.8 | 2 | 1 |
| jitter | 4.7 | 100.9 | 3878.0 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 5.5 | 6.6 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 17.73 | 0.00 | 97.96 |
| cpu1_util_pct | 65.21 | 54.05 | 80.00 |
| cpu2_util_pct | 89.78 | 81.25 | 96.23 |
| cpu3_util_pct | 88.43 | 72.00 | 97.92 |
| ext5v_v | 4.84 | 4.77 | 4.89 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 57.54 | 52.90 | 60.05 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 4.13 | 2.53 | 6.35 |
