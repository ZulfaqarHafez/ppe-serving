add_library(ppe_doctest INTERFACE)
target_include_directories(ppe_doctest SYSTEM INTERFACE "${PROJECT_SOURCE_DIR}/third_party/doctest")

add_executable(ppe_tests
  test_main.cpp
  test_image.cpp
  test_preprocess.cpp
  test_postprocess.cpp
  test_json.cpp
  test_detector.cpp)
target_link_libraries(ppe_tests PRIVATE ppe ppe_doctest ppe_warnings)
target_compile_definitions(ppe_tests PRIVATE
  PPE_TEST_DATA_DIR="${PROJECT_SOURCE_DIR}/data"
  PPE_TEST_MODEL="${PPE_MODEL_PATH}")

# Pure functions: no model needed.
add_test(NAME unit COMMAND ppe_tests --test-suite-exclude=detector)

if(PPE_MODEL_PATH)
  add_test(NAME detector COMMAND ppe_tests --test-suite=detector)
  add_test(NAME cli_exit_codes
    COMMAND bash "${CMAKE_CURRENT_SOURCE_DIR}/cli_exit_codes.sh"
            $<TARGET_FILE:ppe_detect> "${PPE_MODEL_PATH}" "${PROJECT_SOURCE_DIR}/data/samples")
endif()
