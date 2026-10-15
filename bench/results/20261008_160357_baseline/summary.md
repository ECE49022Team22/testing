# Benchmark 20261008_160357_baseline

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_wait_ms | 37826 | 0.58 | 0.86 | 3.32 | 5.92 | 8.53 | 10 | 0 (0.00%) |
| imu | service_ms | 37827 | 0.71 | 1.80 | 4.97 | 8.72 | 15.49 | - |  |
| imu | period_ms | 11953 | 9.98 | 12.49 | 17.58 | 23.07 | 29.84 | 15 | 315 (2.64%) |
| gps | line_gap_ms | 4203 | 1.42 | 190.56 | 194.38 | 195.75 | 211.01 | - |  |
| gps | gga_period_ms | 600 | 200.01 | 201.54 | 203.04 | 210.95 | 218.92 | - |  |
| gps | gga_jitter_ms | 600 | 0.33 | 2.70 | 3.72 | 19.83 | 21.19 | 20 | 1 (0.17%) |
| lidar | scan_period_ms | 1200 | 100.62 | 101.91 | 104.95 | 106.97 | 109.99 | 150 | 0 (0.00%) |
| lidar | excess_ms | 204443 | 0.79 | 1.42 | 3.72 | 6.29 | 11.24 | 10 | 3 (0.00%) |
| yolo | grab_ms | 267 | 2.33 | 3.39 | 5.69 | 7.67 | 7.93 | - |  |
| yolo | infer_ms | 267 | 437.06 | 508.97 | 563.85 | 635.45 | 657.31 | - |  |
| yolo | e2e_ms | 267 | 872.14 | 979.01 | 1017.39 | 1052.95 | 1062.13 | 500 | 267 (100.00%) |
| yolo | loop_ms | 267 | 439.83 | 511.67 | 566.72 | 638.56 | 660.44 | - |  |
| cell | poll_late_ms | 120 | 0.10 | 0.55 | 1.00 | 1.12 | 1.14 | - |  |
| cell | poll_rtt_ms | 120 | 103.25 | 105.16 | 107.49 | 109.53 | 109.80 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 105.80 | 108.43 | 111.38 | 111.68 | 111.71 | - |  |
| motor | telem_period_ms | 1204 | 96.14 | 111.68 | 112.98 | 120.14 | 122.72 | 150 | 0 (0.00%) |
| motor | cmd_rtt_ms | 2250 | 11.32 | 17.89 | 27.24 | 29.69 | 30.96 | 20 | 109 (4.84%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.61 |
| GPS NMEA lines/s | 35.02 |
| LiDAR packets/s | 1703.69 |
| YOLO frames/s | 2.22 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 10.00 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 4292 |
| lidar | bad_timestamps_passed_crc | 18 |
| motor | timeouts | 20 |
| motor | overruns | 20 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 143.5 | 65 | 1940 | 4015 | 6132 | 22.72% | 2.357% |
| cpu1 | 229.1 | 60 | 2753 | 5021 | 8998 | 20.47% | 6.270% |
| cpu2 | 219.9 | 60 | 2728 | 4999 | 10317 | 19.94% | 5.927% |
| cpu3 | 204.8 | 61 | 2636 | 5000 | 8374 | 18.99% | 5.312% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 17.7 | 3321.4 | 1742.4 | 4 | 1,3 |
| gps | 1.0 | 64.7 | 58.4 | 2 | 2 |
| lidar | 30.3 | 1091.2 | 6250.9 | 1 | 2 |
| yolo | 179.4 | 9106.7 | 990.9 | 8 | 0,1,3 |
| cell | 0.2 | 7.6 | 17.5 | 1 | 3 |
| motor | 1.1 | 61.5 | 75.3 | 2 | 2,3 |
| jitter | 4.0 | 116.1 | 3949.4 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 8.2 | 5.5 | 1 | 3 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 88.34 | 68.29 | 100.00 |
| cpu1_util_pct | 63.59 | 38.30 | 94.12 |
| cpu2_util_pct | 65.25 | 47.06 | 90.20 |
| cpu3_util_pct | 70.50 | 54.17 | 96.23 |
| ext5v_v | 4.88 | 4.80 | 4.95 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 56.23 | 51.25 | 60.05 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.75 | 2.59 | 5.24 |
