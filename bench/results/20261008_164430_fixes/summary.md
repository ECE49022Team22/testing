# Benchmark 20261008_164430_fixes

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 37782 | 0.10 | 0.42 | 2.23 | 4.76 | 8.85 | 10 | 0 (0.00%) |
| imu | service_ms | 38040 | 0.70 | 1.93 | 4.86 | 8.30 | 20.56 | - |  |
| imu | period_ms | 11964 | 10.02 | 12.57 | 17.23 | 22.36 | 28.96 | 15 | 349 (2.92%) |
| gps | line_gap_ms | 4087 | 1.43 | 191.19 | 194.41 | 197.34 | 199.36 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 201.49 | 204.86 | 206.20 | 206.51 | - |  |
| gps | gga_jitter_ms | 600 | 0.34 | 2.74 | 5.35 | 6.26 | 6.51 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.63 | 101.78 | 104.38 | 107.42 | 108.89 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215982 | 2.22 | 3.14 | 5.54 | 7.73 | 13.25 | 10 | 32 (0.01%) |
| yolo | grab_ms | 285 | 2.30 | 3.18 | 3.90 | 5.38 | 5.46 | - |  |
| yolo | infer_ms | 285 | 414.89 | 471.63 | 537.92 | 555.92 | 556.78 | - |  |
| yolo | e2e_ms | 285 | 813.76 | 913.63 | 978.18 | 1021.63 | 1025.40 | 500 | 285 (100.00%) |
| yolo | loop_ms | 285 | 417.41 | 474.52 | 540.72 | 558.18 | 559.01 | - |  |
| cell | poll_late_ms | 120 | 0.10 | 0.78 | 2.37 | 3.26 | 3.37 | - |  |
| cell | poll_rtt_ms | 120 | 103.56 | 106.76 | 110.58 | 111.61 | 111.72 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 110.17 | 111.96 | 112.58 | 112.64 | 112.65 | - |  |
| motor | telem_period_ms | 1204 | 99.78 | 100.57 | 102.67 | 104.89 | 107.40 | 150 | 0 (0.00%) |
| motor | cmd_rtt_ms | 2400 | 2.84 | 4.12 | 6.75 | 8.63 | 10.76 | 20 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.70 |
| GPS NMEA lines/s | 34.06 |
| LiDAR packets/s | 1799.84 |
| YOLO frames/s | 2.37 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.94 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 1 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |
| motor | err_replies | 1 |
| motor | timeouts | 1 |
| motor | overruns | 1 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 236.6 | 70 | 2949 | 4974 | 7965 | 30.31% | 6.258% |
| cpu1 | 204.4 | 61 | 2241 | 4147 | 9726 | 20.57% | 5.263% |
| cpu2 | 233.8 | 62 | 2835 | 5012 | 7999 | 20.38% | 6.554% |
| cpu3 | 228.3 | 61 | 2890 | 5000 | 9315 | 19.51% | 6.365% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 19.6 | 2772.7 | 999.0 | 4 | 0,2,3 |
| gps | 0.9 | 21.6 | 56.4 | 2 | 2,3 |
| lidar | 14.1 | 341.8 | 3801.8 | 1 | 3 |
| yolo | 189.0 | 2831.7 | 964.6 | 8 | 0,1,2,3 |
| cell | 0.2 | 3.0 | 17.5 | 1 | 3 |
| motor | 1.4 | 38.0 | 137.5 | 2 | 2,3 |
| jitter | 4.9 | 28.8 | 3948.8 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 2.9 | 5.4 | 1 | 3 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 85.95 | 64.29 | 100.00 |
| cpu1_util_pct | 64.42 | 37.50 | 96.00 |
| cpu2_util_pct | 64.82 | 36.17 | 100.00 |
| cpu3_util_pct | 67.42 | 44.90 | 96.00 |
| ext5v_v | 4.88 | 4.81 | 4.95 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 55.40 | 50.70 | 58.40 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.65 | 2.14 | 5.98 |
