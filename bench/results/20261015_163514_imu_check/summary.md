# Benchmark 20261015_163514_imu_check

Measured window: 15 s

## Latency (ms)

| worker | metric | n | p50 | p90 | p99 | p99.9 | max | budget | over budget |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| imu | int_latency_ms | 4858 | 0.02 | 0.06 | 0.17 | 0.26 | 0.29 | 10 | 0 (0.00%) |
| imu | service_ms | 4858 | 0.32 | 0.44 | 0.87 | 1.31 | 1.53 | - |  |
| imu | period_ms | 1499 | 10.05 | 10.45 | 11.32 | 11.88 | 12.21 | 15 | 0 (0.00%) |

## Throughput

| stream | rate |
|---|---:|
| IMU samples/s | 99.93 |

## Processes

| worker | CPU % (of one core) | involuntary ctx sw/s | voluntary ctx sw/s | threads | cores seen |
|---|---:|---:|---:|---:|---|
| imu | 6.1 | 0.0 | 1021.6 | 4 | 1 |
