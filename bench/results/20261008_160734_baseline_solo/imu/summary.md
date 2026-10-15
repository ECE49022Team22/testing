# Benchmark imu

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_wait_ms | 1133 | 0.56 | 0.57 | 0.62 | 0.89 | 1.79 | 10 | 0 (0.00%) |
| imu | service_ms | 1133 | 0.37 | 0.57 | 1.19 | 2.00 | 284.86 | - |  |
| imu | period_ms | 349 | 10.00 | 10.81 | 12.04 | 13.08 | 13.12 | 15 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 11.63 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 98.4 | 53 | 1987 | 4976 | 5999 | 2.82% | 1.719% |
| cpu1 | 102.8 | 53 | 2000 | 4998 | 6121 | 2.77% | 1.783% |
| cpu2 | 102.8 | 53 | 2004 | 5002 | 8021 | 2.83% | 1.800% |
| cpu3 | 100.8 | 53 | 2000 | 4997 | 6036 | 2.61% | 1.689% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 3.6 | 278.7 | 1848.7 | 4 | 0,2 |
| jitter | 1.7 | 0.5 | 3953.9 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.1 | 4.9 | 1 | 1 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 8.29 | 1.96 | 21.57 |
| cpu1_util_pct | 9.17 | 0.00 | 30.61 |
| cpu2_util_pct | 8.23 | 0.00 | 24.00 |
| cpu3_util_pct | 8.59 | 1.96 | 20.41 |
| ext5v_v | 5.03 | 4.98 | 5.06 |
| freq_mhz | 1805.08 | 1500.00 | 2400.00 |
| temp_c | 48.96 | 47.40 | 50.70 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.31 | 0.89 | 2.00 |
