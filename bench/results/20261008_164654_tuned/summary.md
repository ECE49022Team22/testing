# Benchmark 20261008_164654_tuned

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38978 | 0.10 | 0.22 | 0.41 | 0.73 | 1.31 | 10 | 0 (0.00%) |
| imu | service_ms | 39042 | 0.57 | 1.00 | 1.66 | 2.74 | 5.14 | - |  |
| imu | period_ms | 11983 | 10.05 | 10.99 | 12.26 | 14.08 | 54.61 | 15 | 6 (0.05%) |
| gps | line_gap_ms | 4131 | 1.43 | 190.62 | 193.91 | 195.29 | 195.57 | - |  |
| gps | gga_period_ms | 600 | 200.01 | 200.87 | 203.00 | 203.86 | 204.05 | - |  |
| gps | gga_jitter_ms | 600 | 0.12 | 2.61 | 3.32 | 4.06 | 4.07 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.62 | 101.36 | 103.19 | 104.75 | 106.62 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215979 | 1.23 | 1.91 | 3.71 | 5.78 | 18.37 | 10 | 16 (0.01%) |
| yolo | grab_ms | 283 | 2.36 | 3.13 | 4.25 | 5.11 | 5.19 | - |  |
| yolo | infer_ms | 283 | 415.40 | 467.77 | 512.26 | 622.65 | 659.55 | - |  |
| yolo | e2e_ms | 283 | 821.61 | 908.56 | 958.67 | 1063.08 | 1068.21 | 500 | 283 (100.00%) |
| yolo | loop_ms | 283 | 417.68 | 470.69 | 515.36 | 625.39 | 662.49 | - |  |
| cell | poll_late_ms | 120 | 0.05 | 0.36 | 1.03 | 1.38 | 1.43 | - |  |
| cell | poll_rtt_ms | 120 | 103.03 | 105.71 | 114.80 | 117.84 | 118.17 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 110.60 | 113.57 | 114.87 | 115.00 | 115.02 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.75 | 3.35 | 6.27 | 7.15 | 7.60 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.78 | 100.08 | 102.11 | 104.19 | 105.21 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.86 |
| GPS NMEA lines/s | 34.42 |
| LiDAR packets/s | 1799.82 |
| YOLO frames/s | 2.36 |
| motor telemetry lines/s | 10.03 |
| LiDAR scans/s | 9.94 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| imu | errors | 5 |
| lidar | crc_errors | 0 |
| lidar | rejected | 0 |
| lidar | bad_timestamps_passed_crc | 0 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 236.1 | 71 | 2635 | 4819 | 467669 | 34.32% | 5.638% |
| cpu1 | 198.8 | 61 | 2289 | 4234 | 7763 | 22.39% | 4.789% |
| cpu2 | 205.2 | 61 | 2332 | 4388 | 8316 | 22.62% | 5.019% |
| cpu3 | 201.3 | 61 | 2302 | 4429 | 9013 | 22.26% | 4.922% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 18.7 | 2.3 | 1021.9 | 4 | 2,3 |
| gps | 1.0 | 1.1 | 79.0 | 2 | 0,3 |
| lidar | 15.7 | 8.4 | 5857.4 | 1 | 0 |
| yolo | 182.1 | 4364.6 | 920.1 | 8 | 0,1,2,3 |
| cell | 0.2 | 4.7 | 17.5 | 1 | 3 |
| motor | 1.4 | 0.2 | 159.3 | 2 | 1,3 |
| jitter | 4.8 | 65.0 | 3965.8 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 5.5 | 5.5 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 79.60 | 53.66 | 100.00 |
| cpu1_util_pct | 64.25 | 40.82 | 93.88 |
| cpu2_util_pct | 65.55 | 36.00 | 96.00 |
| cpu3_util_pct | 64.88 | 43.48 | 96.08 |
| ext5v_v | 4.89 | 4.80 | 4.94 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 57.85 | 54.55 | 60.05 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.55 | 2.34 | 4.99 |
