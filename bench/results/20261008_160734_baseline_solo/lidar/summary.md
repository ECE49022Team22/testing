# Benchmark lidar

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lidar | scan_period_ms | 297 | 100.59 | 101.20 | 103.31 | 104.30 | 104.63 | 150 | 0 (0.00%) |
| lidar | excess_ms | 52321 | 0.59 | 0.99 | 1.11 | 3.91 | 7.40 | 10 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| LiDAR packets/s | 1744.03 |
| LiDAR scans/s | 9.90 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| lidar | crc_errors | 303 |
| lidar | bad_timestamps_passed_crc | 1 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 97.8 | 52 | 1850 | 5008 | 6136 | 3.33% | 1.407% |
| cpu1 | 91.7 | 53 | 1744 | 4956 | 6007 | 2.61% | 1.384% |
| cpu2 | 96.9 | 53 | 1981 | 4976 | 6035 | 2.88% | 1.645% |
| cpu3 | 94.9 | 53 | 1967 | 4990 | 6056 | 2.66% | 1.504% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| lidar | 24.3 | 54.8 | 10078.0 | 1 | 1 |
| jitter | 1.4 | 10.0 | 3962.3 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.9 | 4.9 | 1 | 3 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 18.58 | 7.50 | 39.53 |
| cpu1_util_pct | 13.25 | 4.35 | 34.62 |
| cpu2_util_pct | 14.64 | 6.00 | 34.78 |
| cpu3_util_pct | 14.37 | 2.04 | 28.00 |
| ext5v_v | 5.00 | 4.95 | 5.04 |
| freq_mhz | 2277.97 | 1700.00 | 2400.00 |
| temp_c | 48.89 | 47.95 | 50.15 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.79 | 1.28 | 2.92 |
