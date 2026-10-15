# Benchmark gps

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gps | line_gap_ms | 1053 | 1.41 | 190.50 | 193.13 | 194.41 | 194.46 | - |  |
| gps | gga_period_ms | 150 | 200.00 | 200.10 | 202.87 | 202.90 | 202.90 | - |  |
| gps | gga_jitter_ms | 150 | 0.04 | 2.76 | 2.90 | 2.93 | 2.93 | 20 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| GPS NMEA lines/s | 35.10 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 104.0 | 52 | 2008 | 4996 | 6003 | 3.10% | 2.049% |
| cpu1 | 97.1 | 52 | 1990 | 4993 | 6008 | 2.75% | 1.748% |
| cpu2 | 102.1 | 52 | 2004 | 4996 | 6042 | 2.55% | 1.737% |
| cpu3 | 96.0 | 52 | 1987 | 4998 | 6026 | 2.46% | 1.626% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| gps | 0.9 | 0.2 | 71.9 | 2 | 0 |
| jitter | 1.4 | 0.5 | 3959.1 | 5 | 0,1,2,3 |
| sysmon | 0.1 | 0.2 | 5.0 | 1 | 1 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 8.34 | 0.00 | 16.00 |
| cpu1_util_pct | 7.06 | 0.00 | 18.00 |
| cpu2_util_pct | 6.84 | 0.00 | 14.81 |
| cpu3_util_pct | 7.36 | 0.00 | 18.37 |
| ext5v_v | 5.03 | 5.00 | 5.06 |
| freq_mhz | 1877.97 | 1500.00 | 2400.00 |
| temp_c | 48.02 | 46.30 | 50.15 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 1.30 | 0.99 | 2.25 |
