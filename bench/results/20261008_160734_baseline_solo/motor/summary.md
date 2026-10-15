# Benchmark motor

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| motor | telem_period_ms | 301 | 95.92 | 111.65 | 111.80 | 111.86 | 111.88 | 150 | 0 (0.00%) |
| motor | cmd_rtt_ms | 560 | 11.10 | 17.76 | 28.05 | 30.69 | 30.86 | 20 | 31 (5.54%) |

## Throughput

| stream | rate |
|---|---:|
| motor telemetry lines/s | 10.03 |

## Event counters (whole process lifetime)

| worker | counter | count |
|---|---|---:|
| motor | err_replies | 1 |
| motor | timeouts | 5 |
| motor | overruns | 5 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 100.6 | 52 | 2005 | 4988 | 6025 | 2.79% | 1.815% |
| cpu1 | 98.8 | 52 | 1996 | 5000 | 6196 | 2.69% | 1.719% |
| cpu2 | 99.3 | 52 | 1995 | 4992 | 6000 | 2.60% | 1.715% |
| cpu3 | 96.8 | 52 | 1988 | 4999 | 5991 | 2.50% | 1.634% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| motor | 0.9 | 1.1 | 77.5 | 2 | 0,3 |
| jitter | 1.4 | 0.6 | 3957.4 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.2 | 5.0 | 1 | 2 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 8.50 | 1.92 | 34.00 |
| cpu1_util_pct | 7.13 | 0.00 | 14.00 |
| cpu2_util_pct | 7.21 | 0.00 | 17.65 |
| cpu3_util_pct | 6.84 | 0.00 | 14.00 |
| ext5v_v | 5.03 | 4.99 | 5.06 |
| freq_mhz | 1896.61 | 1600.00 | 2400.00 |
| temp_c | 48.20 | 46.85 | 49.60 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.35 | 0.81 | 2.90 |
