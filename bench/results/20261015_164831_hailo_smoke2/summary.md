# Benchmark 20261015_164831_hailo_smoke2

Measured window: 20 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| yolo | grab_ms | 600 | 14.96 | 18.95 | 19.76 | 22.49 | 22.52 | - |  |
| yolo | infer_ms | 600 | 17.14 | 19.42 | 22.83 | 23.67 | 23.72 | - |  |
| yolo | e2e_ms | 600 | 52.25 | 56.11 | 59.55 | 61.76 | 62.09 | 500 | 0 (0.00%) |
| yolo | age_ms | 600 | 34.27 | 38.24 | 39.03 | 41.74 | 41.75 | - |  |
| yolo | loop_ms | 600 | 32.57 | 36.79 | 40.38 | 42.50 | 42.85 | - |  |

## Throughput

| stream | rate |
|---|---:|
| YOLO frames/s | 30.00 |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| yolo | 17.4 | 44.5 | 549.9 | 18 | 2,3 |
