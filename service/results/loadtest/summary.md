# Load test results

Produced by `scripts/loadtest.sh` (k6 closed loop, `loadtest/detect.js`, one
640 x 486 WebP sample per request, keep-alive on) and summarised by
`scripts/summarize_loadtest.py`.

Machine: Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical CPUs, 15.7 GiB RAM, kernel 6.18.44-fc-v445, no GPU; Docker 29.9.2, k6 v1.0.0 (commit/41b4984b75, go1.24.2, linux/amd64). k6 runs on the same host, outside the container's CPU limit. Recorded 2026-11-13T08:57:30Z.

## cpu1-w1t1: 1 CPU, 1 worker x 1 thread (default)

| VUs | requests | throughput (req/s) | p50 ms | p95 ms | p99 ms | error rate | load avg before |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 150 | 10.0 | 98 | 125 | 192 | 0.00% | 0.99 1.59 1.78 |
| 2 | 166 | 10.9 | 169 | 242 | 338 | 0.00% | 0.99 1.56 1.77 |
| 4 | 178 | 11.6 | 332 | 397 | 537 | 0.00% | 0.91 1.50 1.74 |
| 8 | 177 | 11.3 | 675 | 838 | 1034 | 0.00% | 0.93 1.48 1.73 |
| 16 | 189 | 11.4 | 1338 | 1636 | 1664 | 0.00% | 0.95 1.45 1.72 |
| 32 | 191 | 10.8 | 2907 | 3336 | 3399 | 0.00% | 0.96 1.43 1.71 |

Saturation point: 1 VUs (9.98 req/s, p95 124.7 ms); doubling the users from there adds under 10% throughput and over 50% p95. Best throughput at any level: 11.63 req/s (at 4 VUs).

## cpu2-w1t2: 2 CPUs, 1 worker x 2 threads

| VUs | requests | throughput (req/s) | p50 ms | p95 ms | p99 ms | error rate | load avg before |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 245 | 16.3 | 57 | 80 | 98 | 0.00% | 1.12 1.72 1.83 |
| 2 | 267 | 17.7 | 109 | 141 | 172 | 0.00% | 1.17 1.70 1.83 |
| 4 | 262 | 17.2 | 222 | 280 | 380 | 0.00% | 1.35 1.71 1.83 |
| 8 | 256 | 16.5 | 471 | 598 | 692 | 0.00% | 1.82 1.80 1.85 |
| 16 | 258 | 16.1 | 959 | 1163 | 1200 | 0.00% | 1.86 1.81 1.86 |
| 32 | 262 | 15.3 | 2063 | 2288 | 2311 | 0.00% | 1.89 1.82 1.86 |

Saturation point: 1 VUs (16.32 req/s, p95 80.2 ms); doubling the users from there adds under 10% throughput and over 50% p95. Best throughput at any level: 17.7 req/s (at 2 VUs).

## cpu2-w2t1: 2 CPUs, 2 workers x 1 thread (default)

| VUs | requests | throughput (req/s) | p50 ms | p95 ms | p99 ms | error rate | load avg before |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 177 | 11.8 | 81 | 105 | 113 | 0.00% | 0.82 1.94 1.90 |
| 2 | 325 | 21.6 | 87 | 122 | 144 | 0.00% | 0.86 1.89 1.89 |
| 4 | 364 | 24.0 | 158 | 207 | 220 | 0.00% | 1.11 1.90 1.89 |
| 8 | 372 | 24.3 | 317 | 412 | 500 | 0.00% | 1.31 1.89 1.89 |
| 16 | 399 | 25.5 | 617 | 693 | 774 | 0.00% | 1.55 1.91 1.90 |
| 32 | 406 | 24.8 | 1263 | 1422 | 1499 | 0.00% | 1.65 1.92 1.90 |

Saturation point: 4 VUs (24.02 req/s, p95 206.6 ms); doubling the users from there adds under 10% throughput and over 50% p95. Best throughput at any level: 25.54 req/s (at 16 VUs).

## Worker layout under a 2-CPU limit

Best throughput with 2 single-threaded workers: 25.54 req/s; with 1 worker using 2 ONNX Runtime threads: 17.7 req/s; difference +44.3%.
