#!/usr/bin/env bash
# Evidence for the replay path (level b), written to docs/evidence/replay/:
#   samples/<id>_annotated.png and detections.jsonl: the detector (C++, no ROS)
#     on the five sample images at threshold 0.25
#   run.log: 15 s of replay_demo.launch.py on plant-cctv with the fake
#     NavigateToPose server (stand-in for Nav2)
# Run from the repository root with the workspace built and sourced.
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/evidence/replay
mkdir -p "$out/samples"
share=$(ros2 pkg prefix ppe_detector)/share/ppe_detector
samples=$(ros2 pkg prefix ppe_bringup)/share/ppe_bringup/samples
"$(ros2 pkg prefix ppe_detector)/lib/ppe_detector/ppe_detect_image" \
  --model "$share/models/ppe_yolov8s_320_int8dyn.onnx" --threshold 0.25 --out "$out/samples" \
  "$samples"/{site-backs,rooftop-cctv,plant-cctv,hi-vis-walk,packing-cctv}.png \
  > "$out/detections.jsonl"
timeout -s INT 15 ros2 launch ppe_bringup replay_demo.launch.py images:=plant-cctv \
  > "$out/run.raw.log" 2>&1 || true
sed 's/\x1b\[[0-9;]*m//g' "$out/run.raw.log" > "$out/run.log"
rm "$out/run.raw.log"
cat "$out/detections.jsonl"
