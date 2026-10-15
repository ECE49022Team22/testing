# Benchmark 20261008_173459_cores416

Measured window: 120 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 38844 | 0.12 | 0.25 | 0.38 | 0.55 | 0.79 | 10 | 0 (0.00%) |
| imu | service_ms | 38854 | 0.71 | 1.12 | 1.49 | 1.69 | 3.30 | - |  |
| imu | period_ms | 11989 | 10.04 | 11.04 | 12.07 | 13.12 | 14.42 | 15 | 0 (0.00%) |
| gps | line_gap_ms | 4081 | 1.44 | 190.99 | 194.41 | 195.52 | 196.20 | - |  |
| gps | gga_period_ms | 600 | 200.01 | 201.39 | 203.45 | 204.45 | 205.00 | - |  |
| gps | gga_jitter_ms | 600 | 0.33 | 2.63 | 3.75 | 5.88 | 7.20 | 20 | 0 (0.00%) |
| lidar | scan_period_ms | 1193 | 100.61 | 101.43 | 102.97 | 104.73 | 105.16 | 150 | 0 (0.00%) |
| lidar | excess_ms | 215977 | 1.04 | 1.60 | 2.49 | 4.13 | 6.68 | 10 | 0 (0.00%) |
| yolo | grab_ms | 1665 | 0.01 | 0.02 | 8.17 | 12.33 | 13.85 | - |  |
| yolo | infer_ms | 1665 | 71.96 | 87.24 | 107.71 | 152.33 | 204.90 | - |  |
| yolo | e2e_ms | 1665 | 136.99 | 166.99 | 192.38 | 233.07 | 243.13 | 500 | 0 (0.00%) |
| yolo | age_ms | 1665 | 64.87 | 93.06 | 105.37 | 129.05 | 140.83 | - |  |
| yolo | loop_ms | 1665 | 72.10 | 87.83 | 108.43 | 152.36 | 217.15 | - |  |
| cell | poll_late_ms | 120 | 0.07 | 0.38 | 1.77 | 1.94 | 1.96 | - |  |
| cell | poll_rtt_ms | 120 | 103.45 | 105.50 | 107.54 | 108.21 | 108.30 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 8 | 106.81 | 111.21 | 111.35 | 111.36 | 111.37 | - |  |
| motor | cmd_rtt_ms | 2400 | 2.80 | 3.45 | 6.09 | 7.17 | 7.56 | 20 | 0 (0.00%) |
| motor | telem_period_ms | 1204 | 99.76 | 100.11 | 101.37 | 104.57 | 105.32 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.91 |
| GPS NMEA lines/s | 34.01 |
| LiDAR packets/s | 1799.81 |
| YOLO frames/s | 13.87 |
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
| cpu0 | 128.1 | 64 | 1775 | 3661 | 6700 | 21.88% | 2.045% |
| cpu1 | 261.6 | 68 | 2493 | 4466 | 13004 | 39.50% | 6.245% |
| cpu2 | 167.6 | 62 | 1968 | 3888 | 8913 | 21.30% | 3.543% |
| cpu3 | 166.8 | 62 | 1958 | 3763 | 6116 | 21.23% | 3.542% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 23.1 | 0.1 | 1022.0 | 4 | 1 |
| gps | 1.0 | 66.8 | 78.0 | 2 | 1 |
| lidar | 16.8 | 375.4 | 5957.2 | 1 | 1 |
| yolo | 98.0 | 4542.5 | 16114.0 | 10 | 2,3 |
| cell | 0.3 | 4.0 | 17.5 | 1 | 0 |
| motor | 1.6 | 34.9 | 166.0 | 2 | 1 |
| jitter | 4.9 | 63.0 | 3980.7 | 5 | 0,1,2,3 |
| sysmon | 0.3 | 4.7 | 7.1 | 1 | 0 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 45.65 | 21.62 | 71.74 |
| cpu1_util_pct | 50.15 | 40.43 | 64.15 |
| cpu2_util_pct | 77.01 | 66.67 | 86.00 |
| cpu3_util_pct | 76.99 | 66.67 | 85.42 |
| ext5v_v | 4.89 | 4.80 | 4.96 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 58.14 | 55.10 | 60.05 |
| throttled (bitmask) | | 0x50000 | 0x50000 |
| vdd_core_a | 3.55 | 1.84 | 6.55 |
