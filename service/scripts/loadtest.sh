#!/usr/bin/env bash
# Load test the service container on this machine with k6, under a 2-CPU and a
# 1-CPU limit, at several concurrency levels. Each level is a short closed-loop
# run (DURATION, default 15 s) after a 5 s warm-up.
#
#   docker build -t ppe-service:dev .      (first)
#   scripts/loadtest.sh                    (writes results/loadtest/)
#
# Configurations (name | --cpus | environment):
#   cpu2-w2t1  2 CPUs, 2 inference workers x 1 ONNX Runtime thread (the default)
#   cpu2-w1t2  2 CPUs, 1 worker x 2 threads
#   cpu1-w1t1  1 CPU,  1 worker x 1 thread (the default under a 1-CPU limit)
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-ppe-service:dev}
PORT=${PORT:-18080}
DURATION=${DURATION:-15s}
LEVELS=${LEVELS:-"1 2 4 8 16 32"}
CONFIGS=${CONFIGS:-"cpu2-w2t1 cpu2-w1t2 cpu1-w1t1"}
OUT=results/loadtest
mkdir -p "$OUT"
python3 scripts/machine_info.py > "$OUT/machine.json"

env_for() {
  case "$1" in
    cpu2-w2t1) echo "2 2 1" ;;
    cpu2-w1t2) echo "2 1 2" ;;
    cpu1-w1t1) echo "1 1 1" ;;
    *) echo "unknown config $1" >&2; exit 2 ;;
  esac
}

# Other work on the host skews the numbers; wait (up to 3 min) for the 1-minute
# load average to fall below QUIET_LOAD before each configuration.
wait_quiet() {
  for _ in $(seq 1 36); do
    awk -v q="${QUIET_LOAD:-1.0}" '{exit !($1 < q)}' /proc/loadavg && return 0
    sleep 5
  done
  echo "host still busy: $(cut -d' ' -f1-3 /proc/loadavg)" >&2
}

wait_ready() {
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORT/readyz" >/dev/null && return 0
    sleep 0.5
  done
  echo "service did not become ready" >&2; return 1
}

for cfg in $CONFIGS; do
  read -r cpus workers threads < <(env_for "$cfg")
  mkdir -p "$OUT/$cfg"
  docker rm -f ppe-load >/dev/null 2>&1 || true
  wait_quiet
  docker run -d --name ppe-load --cpus "$cpus" -p "127.0.0.1:$PORT:8000" \
    -e PPE_WORKERS="$workers" -e PPE_INTRA_OP_THREADS="$threads" -e PPE_LOG_LEVEL=WARNING \
    "$IMAGE" >/dev/null
  trap 'docker rm -f ppe-load >/dev/null 2>&1 || true' EXIT
  wait_ready
  k6 run -q -e BASE_URL="http://127.0.0.1:$PORT" -e VUS=2 -e DURATION=5s loadtest/detect.js >/dev/null 2>&1
  for vus in $LEVELS; do
    load=$(cut -d' ' -f1-3 /proc/loadavg)
    k6 run -q -e BASE_URL="http://127.0.0.1:$PORT" -e VUS="$vus" -e DURATION="$DURATION" \
      -e LABEL="$cfg cpus=$cpus workers=$workers intra_op_threads=$threads loadavg_before=$load" \
      -e SUMMARY="$OUT/$cfg/vus-$vus.json" loadtest/detect.js 2>/dev/null | tail -1
  done
  docker rm -f ppe-load >/dev/null
done
python3 scripts/summarize_loadtest.py "$OUT"
