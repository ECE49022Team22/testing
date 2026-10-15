# Benchmark 20261008_173246_cores

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38827 | 0.14 | 0.26 | 0.36 | 0.43 | 0.60 | 10 | 0 (0.00%) |
| imu | service_ms | 38856 | 0.78 | 1.26 | 1.68 | 1.98 | 3.86 | - |  |
| imu | period_ms | 11990 | 10.02 | 11.25 | 12.54 | 13.39 | 15.19 | 15 | 1 (0.01%) |
| gps | line_gap_ms | 4112 | 1.44 | 190.66 | 194.68 | 196.95 | 198.92 | - |  |
| gps | gga_period_ms | 600 | 200.00 | 201.84 | 204.95 | 207.67 | 208.23 | - |  |
| gps | gga_jitter_ms | 600 | 0.50 | 2.90 | 6.12 | 8.26 | 8.31 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.61 | 101.87 | 103.64 | 105.49 | 106.16 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215977 | 1.08 | 1.72 | 3.23 | 5.17 | 9.92 | 10 | 0 (0.00%) |
| yolo | grab_ms | 786 | 0.01 | 0.01 | 0.04 | 0.06 | 0.10 | - |  |
| yolo | infer_ms | 786 | 150.42 | 173.88 | 193.13 | 234.77 | 274.93 | - |  |
| yolo | e2e_ms | 786 | 225.37 | 258.79 | 310.83 | 368.27 | 379.89 | 500 | 0 (0.00%) |
| yolo | age_ms | 786 | 72.20 | 102.90 | 159.54 | 176.67 | 184.32 | - |  |
| yolo | loop_ms | 786 | 150.44 | 173.90 | 193.14 | 234.81 | 274.95 | - |  |
| cell | poll_late_ms | 120 | 0.10 | 0.58 | 1.69 | 2.88 | 3.02 | - |  |
| cell | poll_rtt_ms | 120 | 104.16 | 107.09 | 109.79 | 150.44 | 155.91 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 112.21 | 115.50 | 117.20 | 117.37 | 117.39 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.89 | 3.73 | 6.29 | 7.09 | 8.37 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.74 | 100.25 | 102.07 | 103.14 | 103.20 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.92 |
| GPS NMEA lines/s | 34.27 |
| LiDAR packets/s | 1799.80 |
| YOLO frames/s | 6.55 |
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
| cpu0 | 162.9 | 70 | 2602 | 4910 | 10864 | 26.89% | 2.987% |
| cpu1 | 356.9 | 77 | 3182 | 6226 | 18877 | 44.77% | 10.162% |
| cpu2 | 195.7 | 65 | 2189 | 3895 | 7956 | 22.96% | 4.425% |
| cpu3 | 227.7 | 65 | 2693 | 4613 | 9345 | 24.45% | 5.650% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 26.1 | 0.0 | 1022.5 | 4 | 1 |
| gps | 1.1 | 70.3 | 67.3 | 2 | 1 |
| lidar | 18.4 | 416.4 | 5246.5 | 1 | 1 |
| yolo | 105.6 | 2888.1 | 7685.7 | 10 | 2,3 |
| cell | 0.4 | 4.0 | 17.5 | 1 | 0 |
| motor | 1.9 | 42.1 | 159.1 | 2 | 1 |
| jitter | 5.8 | 72.1 | 3950.6 | 5 | 0,1,2,3 |
| sysmon | 0.3 | 5.5 | 6.7 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 52.78 | 32.43 | 84.78 |
| cpu1_util_pct | 54.88 | 45.45 | 66.10 |
| cpu2_util_pct | 81.49 | 66.67 | 88.00 |
| cpu3_util_pct | 80.51 | 68.75 | 90.57 |
| ext5v_v | 4.87 | 4.76 | 4.94 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 58.31 | 54.00 | 60.05 |
| throttled (bitmask) | | 0x50000 | 0x50000 |
| vdd_core_a | 3.87 | 2.10 | 6.53 |
