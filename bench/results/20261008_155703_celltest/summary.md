# Benchmark 20261008_155703_celltest

Measured window: 10 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cell | poll_late_ms | 10 | 0.08 | 0.09 | 0.09 | 0.09 | 0.09 | - |  |
| cell | poll_rtt_ms | 10 | 101.63 | 103.87 | 106.79 | 107.08 | 107.11 | 500 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| cell | 0.1 | 0.6 | 17.0 | 1 | 2 |
