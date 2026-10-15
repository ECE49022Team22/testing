# Benchmark cell

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cell | poll_late_ms | 30 | 0.08 | 0.11 | 0.73 | 0.74 | 0.74 | - |  |
| cell | poll_rtt_ms | 30 | 101.54 | 101.89 | 102.55 | 102.73 | 102.74 | 500 | 0 (0.00%) |
| cell | status_rtt_ms | 2 | 106.25 | 108.66 | 109.20 | 109.25 | 109.26 | - |  |

## Throughput

| stream | rate |
|---|---:|

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 105.8 | 52 | 2007 | 4999 | 6027 | 3.15% | 1.949% |
| cpu1 | 100.1 | 52 | 1990 | 4996 | 6036 | 2.80% | 1.797% |
| cpu2 | 103.8 | 52 | 2014 | 5000 | 7029 | 2.83% | 1.881% |
| cpu3 | 103.4 | 52 | 2003 | 5001 | 6057 | 2.81% | 1.869% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| cell | 0.1 | 0.1 | 17.5 | 1 | 0 |
| jitter | 1.4 | 0.7 | 3953.2 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.2 | 5.0 | 1 | 1 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 9.59 | 0.00 | 42.86 |
| cpu1_util_pct | 8.74 | 0.00 | 31.37 |
| cpu2_util_pct | 9.99 | 0.00 | 91.84 |
| cpu3_util_pct | 9.29 | 1.96 | 34.69 |
| ext5v_v | 5.04 | 4.95 | 5.06 |
| freq_mhz | 1893.22 | 1600.00 | 2400.00 |
| temp_c | 49.43 | 46.85 | 51.80 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.35 | 0.85 | 3.39 |
