#!/usr/bin/env bash
# Drive load at the compose stack and capture the Grafana dashboard while it runs.
#   docker compose up -d   (first)
#   scripts/dashboard_under_load.sh
# Phases: 90 s at 4 users, 45 s at 48 users (above the in-flight cap of 32, so
# some requests get 503), then 60 s at 8 users with the screenshot taken near
# the end. Writes docs/grafana-dashboard.png and results/dashboard_load.jsonl.
set -euo pipefail
cd "$(dirname "$0")/.."
URL=${BASE_URL:-http://127.0.0.1:8000}
mkdir -p results docs
: > results/dashboard_load.jsonl
run() { k6 run -q -e BASE_URL="$URL" -e VUS="$1" -e DURATION="$2" -e LABEL="dashboard phase $1 VUs" \
          loadtest/detect.js 2>/dev/null | tail -1 >> results/dashboard_load.jsonl; }
run 4 90s
run 48 45s
run 8 60s &
sleep 50
node scripts/screenshot_dashboard.js docs/grafana-dashboard.png
wait
cat results/dashboard_load.jsonl
