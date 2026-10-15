# Benchmark 20261008_161248_idle

Measured window: 20 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Throughput

| stream | rate |
|---|---:|

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 101.8 | 52 | 2000 | 5000 | 6014 | 2.77% | 1.849% |
| cpu1 | 96.2 | 52 | 1977 | 5002 | 6009 | 2.32% | 1.561% |
| cpu2 | 100.6 | 52 | 2008 | 4993 | 6011 | 2.67% | 1.869% |
| cpu3 | 103.3 | 52 | 2009 | 4999 | 5999 | 2.55% | 1.794% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| jitter | 1.4 | 0.6 | 3955.1 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.2 | 5.0 | 1 | 3 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 6.59 | 1.89 | 14.29 |
| cpu1_util_pct | 6.73 | 0.00 | 13.46 |
| cpu2_util_pct | 6.75 | 1.92 | 14.29 |
| cpu3_util_pct | 7.97 | 0.00 | 16.00 |
| ext5v_v | 5.03 | 4.99 | 5.06 |
| freq_mhz | 1787.50 | 1500.00 | 2400.00 |
| temp_c | 46.40 | 44.65 | 47.95 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.29 | 0.96 | 1.76 |
