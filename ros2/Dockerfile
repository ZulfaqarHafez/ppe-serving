# Builds the workspace, runs the tests and the replay demo:
#   docker build -t ppe-ros2 .
#   docker run --rm ppe-ros2            # tests, then a 20 s replay demo
# The Gazebo + Nav2 demo is not in this image (see README).
FROM ros:jazzy-ros-base

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-vision-msgs ros-jazzy-cv-bridge ros-jazzy-onnxruntime-vendor \
      ros-jazzy-nav2-msgs ros-jazzy-ament-lint-auto ros-jazzy-ament-lint-common \
      ros-jazzy-ament-cmake-gtest ros-jazzy-launch-testing-ament-cmake \
      ros-jazzy-launch-testing-ros libopencv-dev python3-opencv curl libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
COPY src src
COPY scripts scripts
COPY docker docker
# The model is downloaded at configure time and checked against its SHA-256.
# Behind a TLS-intercepting proxy, pass its CA bundle as a build secret:
#   docker build --secret id=extra_ca,src=/path/to/ca.crt -t ppe-ros2 .
RUN --mount=type=secret,id=extra_ca,required=false \
    . /opt/ros/jazzy/setup.sh \
    && ca="" && if [ -s /run/secrets/extra_ca ]; then ca="-DCMAKE_TLS_CAINFO=/run/secrets/extra_ca"; fi \
    && colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release $ca

# cppcheck 2.13 (Ubuntu 24.04) is skipped by ament_cppcheck unless allowed.
ENV AMENT_CPPCHECK_ALLOW_SLOW_VERSIONS=1
ENTRYPOINT ["/ws/docker/entrypoint.sh"]
CMD ["all"]
