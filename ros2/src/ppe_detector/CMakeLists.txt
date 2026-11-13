cmake_minimum_required(VERSION 3.16)
project(ppe_detector LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(lifecycle_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(vision_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs)
find_package(onnxruntime_vendor REQUIRED)

# The model is not committed. It is fetched from the public site and checked
# against a pinned SHA-256; pass -DPPE_MODEL_FILE=/path/to/file to use a local
# copy (it must match the same hash).
set(PPE_MODEL_NAME "ppe_yolov8s_320_int8dyn.onnx")
set(PPE_MODEL_URL "https://zulfaqarhafez.com/models/ppe/${PPE_MODEL_NAME}"
  CACHE STRING "Where to download the PPE model")
set(PPE_MODEL_SHA256 "d0a6c62f4bda6733f443b22bf9dce288b8f082ca0fc2f404a4931eb7cf0cbac2")
set(PPE_MODEL_FILE "" CACHE FILEPATH "Local copy of the PPE model (optional)")
set(PPE_MODEL_PATH "${CMAKE_CURRENT_BINARY_DIR}/models/${PPE_MODEL_NAME}")
if(PPE_MODEL_FILE)
  file(SHA256 "${PPE_MODEL_FILE}" _hash)
  if(NOT _hash STREQUAL PPE_MODEL_SHA256)
    message(FATAL_ERROR "${PPE_MODEL_FILE} has SHA-256 ${_hash}, expected ${PPE_MODEL_SHA256}")
  endif()
  configure_file("${PPE_MODEL_FILE}" "${PPE_MODEL_PATH}" COPYONLY)
elseif(NOT EXISTS "${PPE_MODEL_PATH}")
  message(STATUS "Downloading ${PPE_MODEL_URL}")
  file(DOWNLOAD "${PPE_MODEL_URL}" "${PPE_MODEL_PATH}"
    EXPECTED_HASH SHA256=${PPE_MODEL_SHA256} TLS_VERIFY ON SHOW_PROGRESS)
endif()

add_library(ppe_core src/ppe_core.cpp src/onnx_detector.cpp)
target_include_directories(ppe_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}>)
target_link_libraries(ppe_core PUBLIC onnxruntime::onnxruntime)

add_executable(ppe_detector_node src/ppe_detector_node.cpp)
target_link_libraries(ppe_detector_node ppe_core
  rclcpp::rclcpp rclcpp_lifecycle::rclcpp_lifecycle ${lifecycle_msgs_TARGETS}
  ${sensor_msgs_TARGETS} ${std_msgs_TARGETS} ${vision_msgs_TARGETS}
  cv_bridge::cv_bridge opencv_core opencv_imgproc ament_index_cpp::ament_index_cpp)

# Command-line check on still images: prints detections as JSON and can write
# an annotated PNG. Used for the parity numbers and the evidence frames.
add_executable(ppe_detect_image src/ppe_detect_image.cpp)
target_link_libraries(ppe_detect_image ppe_core opencv_core opencv_imgproc opencv_imgcodecs)

install(TARGETS ppe_core EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(TARGETS ppe_detector_node ppe_detect_image DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include/${PROJECT_NAME})
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
install(FILES "${PPE_MODEL_PATH}" DESTINATION share/${PROJECT_NAME}/models)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # Exceptions, listed in the README:
  # - copyright: no licence has been chosen yet, so files carry no copyright
  #   header; cpplint runs with its legal/copyright check off for the same reason.
  # - xmllint: this libxml2 cannot fetch the package.xml schema over http;
  #   scripts/check_package_xml.sh validates against a fetched copy instead.
  list(APPEND AMENT_LINT_AUTO_EXCLUDE
    ament_cmake_copyright ament_cmake_cpplint ament_cmake_xmllint)
  ament_lint_auto_find_test_dependencies()
  find_package(ament_cmake_cpplint REQUIRED)
  ament_cpplint(FILTERS "-legal/copyright")

  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_ppe_core test/test_ppe_core.cpp)
  target_link_libraries(test_ppe_core ppe_core)

  ament_add_gtest(test_parity test/test_parity.cpp TIMEOUT 120)
  target_link_libraries(test_parity ppe_core opencv_core opencv_imgproc opencv_imgcodecs)
  target_compile_definitions(test_parity PRIVATE
    PPE_MODEL="${PPE_MODEL_PATH}"
    PPE_SAMPLES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../ppe_bringup/samples")
endif()

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(onnxruntime_vendor)
ament_package()
