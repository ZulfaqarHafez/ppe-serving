# Measurements

Measured by `scripts/measure.py` on 2026-11-12 07:06 UTC. Raw values: `results/benchmark.json`.

## Machine

- CPU: Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical CPUs (1 thread(s) per core), no GPU used
- RAM: 15.7 GiB
- OS: Ubuntu 24.04.5 LTS, kernel 6.18.44-fc-v378
- ROS 2 jazzy, ONNX Runtime 1.24.3 (CPU execution provider)

## Detector node

| intra-op threads | image QoS | offered fps | processed fps | latency p50 ms | latency p95 ms | inference p50 ms | inference p95 ms | CPU % of one core |
|---|---|---|---|---|---|---|---|---|
| 1 | reliable | 50.0 | 24.3 | 47.49 | 64.84 | 31.92 | 46.75 | 100.4 |
| 1 | reliable | 5.0 | 5.0 | 52.91 | 72.11 | 37.21 | 52.14 | 21.4 |
| default | reliable | 50.0 | 31.57 | 41.21 | 52.02 | 24.37 | 32.71 | 386.8 |
| default | reliable | 5.0 | 5.0 | 48.5 | 58.05 | 33.15 | 41.28 | 102.4 |
| default | best_effort | 5.0 | 0.87 | 41.78 | 49.26 | 34.47 | 44.23 | 18.3 |

Latency: image header stamp to Detection2DArray received by the measuring script (two DDS hops, colour conversion, letterbox, inference, decode, NMS). At 50 offered fps the node is saturated and keeps only the newest frame, so processed fps is its throughput.

## Detection to goal (replayed images, fake NavigateToPose server)

- goals sent in 60.0 s: 38 (succeeded: 38)
- frame that completed the run of 3 to goal sent: p50 47.57 ms, p95 58.26 ms
- first frame of the run to goal sent (includes waiting for 3 frames at 5.0 fps): p50 447.77 ms, p95 458.35 ms
