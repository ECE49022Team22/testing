# Benchmark yolo

Measured window: 30 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| yolo | grab_ms | 89 | 2.28 | 2.54 | 3.17 | 3.43 | 3.46 | - |  |
| yolo | infer_ms | 89 | 331.06 | 347.32 | 382.61 | 395.12 | 396.51 | - |  |
| yolo | e2e_ms | 89 | 653.46 | 674.00 | 721.08 | 743.03 | 745.46 | 500 | 89 (100.00%) |
| yolo | loop_ms | 89 | 333.35 | 349.67 | 384.85 | 397.46 | 398.87 | - |  |

## Throughput

| stream | rate |
|---|---:|
| YOLO frames/s | 2.97 |

## Scheduling latency, 1 kHz timer per core (µs)

| core | mean | p50 | p99 | p99.9 | max | >100 µs | >1 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu0 | 271.1 | 62 | 3012 | 4992 | 7057 | 20.75% | 8.542% |
| cpu1 | 257.0 | 62 | 3014 | 5022 | 8993 | 17.97% | 7.955% |
| cpu2 | 247.9 | 62 | 3005 | 5035 | 7974 | 16.96% | 7.548% |
| cpu3 | 281.7 | 61 | 3020 | 5034 | 8373 | 20.19% | 8.988% |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| yolo | 206.6 | 1633.7 | 842.4 | 8 | 1,2,3 |
| jitter | 4.6 | 1.6 | 3920.6 | 5 | 0,1,2,3 |
| sysmon | 0.2 | 1.1 | 5.3 | 1 | 2 |

## System

| signal | mean | min | max |
|---|---:|---:|---:|
| cpu0_util_pct | 64.57 | 33.33 | 100.00 |
| cpu1_util_pct | 61.60 | 34.00 | 98.11 |
| cpu2_util_pct | 65.88 | 29.17 | 100.00 |
| cpu3_util_pct | 58.61 | 38.30 | 100.00 |
| ext5v_v | 4.89 | 4.81 | 4.93 |
| freq_mhz | 2400.00 | 2400.00 | 2400.00 |
| temp_c | 53.65 | 50.70 | 55.10 |
| throttled (bitmask) | | 0x0 | 0x0 |
| vdd_core_a | 3.77 | 2.76 | 5.20 |
