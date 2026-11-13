#!/usr/bin/env bash
# Container entry point.
#   test : colcon test (unit, parity, launch and lint tests) and package.xml schema check
#   demo : replay demo (sample images, detector, patrol, fake Nav2 server) for DEMO_SECONDS
#   all  : test, then demo (default)
#   anything else is run as a command
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash
cd /ws

run_tests() {
  colcon test --event-handlers console_direct- --return-code-on-test-failure
  colcon test-result --verbose
  scripts/check_package_xml.sh
}

run_demo() {
  timeout -s INT "${DEMO_SECONDS:-20}" \
    ros2 launch ppe_bringup replay_demo.launch.py images:="${DEMO_IMAGES:-plant-cctv}" || true
}

case "${1:-all}" in
  test) run_tests ;;
  demo) run_demo ;;
  all) run_tests; run_demo ;;
  *) exec "$@" ;;
esac
