cmake_minimum_required(VERSION 3.16)
project(ppe_bringup LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs)

add_executable(sample_image_publisher src/sample_image_publisher.cpp)
target_link_libraries(sample_image_publisher rclcpp::rclcpp ${sensor_msgs_TARGETS}
  ament_index_cpp::ament_index_cpp opencv_core opencv_imgproc opencv_imgcodecs)

add_executable(fake_navigate_to_pose_server src/fake_navigate_to_pose_server.cpp)
target_link_libraries(fake_navigate_to_pose_server rclcpp::rclcpp rclcpp_action::rclcpp_action
  ${nav2_msgs_TARGETS})

install(TARGETS sample_image_publisher fake_navigate_to_pose_server
  DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch config samples worlds DESTINATION share/${PROJECT_NAME})

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

  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_violation_sends_goal.py TIMEOUT 120)
  add_launch_test(test/test_compliant_no_goal.py TIMEOUT 120)
  add_launch_test(test/test_node_parity.py TIMEOUT 120)
endif()

ament_package()
