# Benchmark 20261008_161217_imu_solo_retry2

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_wait_ms | 9716 | 0.57 | 0.57 | 0.61 | 3.23 | 6.11 | 10 | 0 (0.00%) |
| imu | service_ms | 9716 | 0.40 | 0.58 | 1.18 | 1.85 | 6.20 | - |  |
| imu | period_ms | 2998 | 10.05 | 10.79 | 11.91 | 14.11 | 17.61 | 15 | 2 (0.07%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 103.3 | 53 | 1998 | 4981 | 6057 | 3.64% | 1.816% |
| cpu1 | 97.5 | 53 | 1979 | 5003 | 7649 | 3.27% | 1.591% |
| cpu2 | 104.7 | 53 | 2008 | 4999 | 6029 | 3.45% | 1.857% |
| cpu3 | 104.3 | 53 | 2007 | 5002 | 6019 | 3.31% | 1.807% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 9.9 | 2357.7 | 2202.5 | 4 | 0,2,3 |
| jitter | 1.7 | 1.3 | 3957.5 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.1 | 5.0 | 1 | 2 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 10.61 | 2.17 | 29.17 |
| cpu1_util_pct | 9.97 | 3.92 | 26.00 |
| cpu2_util_pct | 10.75 | 2.04 | 24.00 |
| cpu3_util_pct | 11.14 | 2.04 | 34.69 |
| ext5v_v | 5.04 | 4.96 | 5.06 |
| freq_mhz | 1850.85 | 1600.00 | 2400.00 |
| temp_c | 46.80 | 45.75 | 47.95 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.23 | 0.98 | 2.31 |
