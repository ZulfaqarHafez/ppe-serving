cmake_minimum_required(VERSION 3.16)
project(ppe_patrol LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(vision_msgs REQUIRED)

add_library(patrol_logic src/patrol_logic.cpp)
target_include_directories(patrol_logic PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}>)

add_executable(ppe_patrol_node src/ppe_patrol_node.cpp)
target_link_libraries(ppe_patrol_node patrol_logic
  rclcpp::rclcpp rclcpp_action::rclcpp_action
  ${nav2_msgs_TARGETS} ${std_msgs_TARGETS} ${vision_msgs_TARGETS})

install(TARGETS patrol_logic EXPORT export_${PROJECT_NAME}
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(TARGETS ppe_patrol_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include/${PROJECT_NAME})
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})

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
  ament_add_gtest(test_patrol_logic test/test_patrol_logic.cpp)
  target_link_libraries(test_patrol_logic patrol_logic)
endif()

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_package()
