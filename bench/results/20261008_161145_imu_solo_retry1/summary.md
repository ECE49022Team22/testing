# Benchmark 20261008_161145_imu_solo_retry1

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_wait_ms | 9714 | 0.57 | 0.57 | 0.61 | 2.98 | 10.82 | 10 | 1 (0.01%) |
| imu | service_ms | 9714 | 0.39 | 0.58 | 1.17 | 1.77 | 6.22 | - |  |
| imu | period_ms | 2998 | 10.04 | 10.77 | 11.99 | 13.64 | 20.69 | 15 | 3 (0.10%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 105.2 | 53 | 2008 | 4999 | 6043 | 3.58% | 1.958% |
| cpu1 | 103.0 | 53 | 2008 | 5005 | 6043 | 3.47% | 1.810% |
| cpu2 | 100.0 | 53 | 2000 | 5004 | 6978 | 3.08% | 1.663% |
| cpu3 | 97.2 | 53 | 1972 | 4990 | 10060 | 3.26% | 1.593% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 9.8 | 2352.2 | 2204.5 | 4 | 1,3 |
| jitter | 1.7 | 1.3 | 3954.7 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.2 | 4.9 | 1 | 3 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 10.72 | 2.04 | 23.53 |
| cpu1_util_pct | 10.36 | 2.04 | 26.00 |
| cpu2_util_pct | 11.43 | 2.00 | 34.00 |
| cpu3_util_pct | 10.43 | 2.08 | 28.85 |
| ext5v_v | 5.03 | 4.98 | 5.07 |
| freq_mhz | 1893.22 | 1600.00 | 2400.00 |
| temp_c | 47.06 | 45.75 | 48.50 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.55 | 0.86 | 2.62 |
