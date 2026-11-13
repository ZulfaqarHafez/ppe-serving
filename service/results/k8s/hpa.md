# HPA on kind: keep-alive against no keep-alive

Produced by `scripts/kind_hpa.py`: k6 with 8 users for 150 s from the host
against the NodePort (so through kube-proxy), one kind node on the machine in
`results/loadtest/machine.json`. Pod CPU request 500m, limit 1; HPA target 60% CPU,
1 to 4 replicas. Raw samples every 10 s are in `hpa-keepalive.json` and
`hpa-no-keepalive.json`.

| mode | requests | throughput (req/s) | p95 ms | error rate | max replicas | busiest pod share | requests per pod |
|---|---:|---:|---:|---:|---:|---:|---|
| keepalive | 1832 | 12.2 | 743 | 0.00% | 4 | 100.0% | 1832, 0, 0, 0 |
| no-keepalive | 4546 | 30.2 | 659 | 0.00% | 4 | 31.6% | 1435, 1136, 1133, 842 |

Replicas over time (seconds since the load started):

- keepalive: 0s: 1 (0% CPU), 10s: 1 (0% CPU), 20s: 1 (32% CPU), 31s: 1 (198% CPU), 41s: 1 (198% CPU), 51s: 4 (198% CPU), 62s: 4 (100% CPU), 72s: 4 (100% CPU), 83s: 4 (50% CPU), 93s: 4 (50% CPU), 103s: 4 (50% CPU), 114s: 4 (50% CPU), 124s: 4 (49% CPU), 134s: 4 (50% CPU), 145s: 4 (50% CPU), 151s: 4 (50% CPU)
- no-keepalive: 0s: 1 (0% CPU), 10s: 1 (0% CPU), 20s: 1 (0% CPU), 31s: 1 (151% CPU), 41s: 1 (151% CPU), 51s: 3 (198% CPU), 62s: 3 (172% CPU), 72s: 4 (167% CPU), 83s: 4 (167% CPU), 93s: 4 (156% CPU), 104s: 4 (151% CPU), 114s: 4 (151% CPU), 125s: 4 (159% CPU), 135s: 4 (157% CPU), 145s: 4 (157% CPU), 151s: 4 (150% CPU)
