# Benchmark 20261008_173031_yolo

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38675 | 0.14 | 0.26 | 0.47 | 0.80 | 1.19 | 10 | 0 (0.00%) |
| imu | service_ms | 38806 | 0.76 | 1.22 | 2.02 | 3.40 | 6.46 | - |  |
| imu | period_ms | 11990 | 10.05 | 11.13 | 12.64 | 14.11 | 15.62 | 15 | 2 (0.02%) |
| gps | line_gap_ms | 4100 | 1.45 | 190.78 | 193.55 | 194.86 | 195.19 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 200.51 | 203.05 | 204.98 | 205.87 | - |  |
| gps | gga_jitter_ms | 600 | 0.13 | 2.63 | 3.16 | 5.91 | 5.98 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.60 | 101.26 | 102.38 | 104.51 | 105.55 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215977 | 1.03 | 1.59 | 2.77 | 4.81 | 7.27 | 10 | 0 (0.00%) |
| yolo | grab_ms | 595 | 0.01 | 0.02 | 0.07 | 0.20 | 0.22 | - |  |
| yolo | infer_ms | 595 | 202.10 | 231.90 | 260.41 | 285.47 | 286.50 | - |  |
| yolo | e2e_ms | 595 | 345.19 | 409.88 | 450.01 | 463.54 | 466.18 | 500 | 0 (0.00%) |
| yolo | age_ms | 595 | 141.62 | 201.87 | 239.78 | 259.74 | 274.38 | - |  |
| yolo | loop_ms | 595 | 202.13 | 231.91 | 260.42 | 285.49 | 286.53 | - |  |
| cell | poll_late_ms | 120 | 0.07 | 0.70 | 1.16 | 1.39 | 1.42 | - |  |
| cell | poll_rtt_ms | 120 | 103.69 | 106.45 | 109.63 | 112.57 | 112.92 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 110.96 | 112.53 | 113.15 | 113.21 | 113.22 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.79 | 3.30 | 6.18 | 7.83 | 9.17 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.75 | 100.01 | 101.37 | 104.43 | 105.36 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.92 |
| GPS NMEA lines/s | 34.17 |
| LiDAR packets/s | 1799.80 |
| YOLO frames/s | 4.96 |
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
| cpu0 | 246.6 | 89 | 2395 | 4707 | 9291 | 45.03% | 5.081% |
| cpu1 | 182.9 | 66 | 2023 | 4012 | 7504 | 27.17% | 3.321% |
| cpu2 | 189.4 | 67 | 2036 | 3992 | 9351 | 29.01% | 3.408% |
| cpu3 | 181.3 | 67 | 1967 | 3866 | 9735 | 29.06% | 3.058% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 25.8 | 10.1 | 1016.5 | 4 | 0,1,2,3 |
| gps | 1.6 | 2.3 | 81.4 | 2 | 3 |
| lidar | 21.9 | 24.3 | 5685.7 | 1 | 2 |
| yolo | 110.0 | 2896.3 | 5768.6 | 10 | 0,1,2,3 |
| cell | 0.2 | 6.6 | 17.5 | 1 | 3 |
| motor | 2.1 | 0.4 | 165.2 | 2 | 0,3 |
| jitter | 6.2 | 94.3 | 3973.1 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 6.4 | 5.5 | 1 | 1 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 85.13 | 75.56 | 93.88 |
| cpu1_util_pct | 64.11 | 51.06 | 90.20 |
| cpu2_util_pct | 64.32 | 51.16 | 77.55 |
| cpu3_util_pct | 62.35 | 48.94 | 82.35 |
| ext5v_v | 4.92 | 4.74 | 4.99 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 54.35 | 50.70 | 56.75 |
| throttled (bitmask) | | 0x50000 | 0x50005 |
| vdd_core_a | 3.55 | 0.77 | 7.05 |
