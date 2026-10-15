# Benchmark 20261008_163921_pre_reboot_check

Measured window: 15 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 4858 | 0.03 | 0.09 | 0.27 | 2.32 | 3.38 | 10 | 0 (0.00%) |
| imu | service_ms | 4858 | 0.41 | 0.60 | 1.25 | 1.49 | 1.76 | - |  |
| imu | period_ms | 1499 | 10.05 | 10.68 | 12.10 | 13.16 | 14.38 | 15 | 0 (0.00%) |
| motor | cmd_rtt_ms | 301 | 11.40 | 17.62 | 24.92 | 28.57 | 29.25 | 20 | 13 (4.32%) |
| motor | telem_period_ms | 150 | 95.87 | 111.65 | 111.98 | 122.05 | 123.80 | 150 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |
| motor telemetry lines/s | 10.00 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 93.8 | 53 | 1708 | 4221 | 5708 | 3.37% | 1.553% |
| cpu1 | 100.1 | 53 | 1969 | 5000 | 5993 | 3.69% | 1.610% |
| cpu2 | 103.9 | 53 | 2010 | 4988 | 5985 | 3.55% | 1.855% |
| cpu3 | 90.6 | 53 | 1445 | 4992 | 6018 | 3.86% | 1.277% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 9.6 | 2374.4 | 1021.6 | 4 | 0,1,2 |
| motor | 0.9 | 3.8 | 80.8 | 2 | 0,3 |
| jitter | 1.7 | 1.9 | 3966.4 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.3 | 5.2 | 1 | 1 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 10.97 | 0.00 | 24.49 |
| cpu1_util_pct | 11.10 | 4.08 | 24.49 |
| cpu2_util_pct | 12.16 | 4.08 | 26.53 |
| cpu3_util_pct | 10.57 | 2.13 | 34.00 |
| ext5v_v | 5.02 | 4.94 | 5.05 |
| freq_mhz | 1883.33 | 1600.00 | 2400.00 |
| temp_c | 47.33 | 46.30 | 48.50 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 0.98 | 0.80 | 1.07 |
