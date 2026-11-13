cmake_minimum_required(VERSION 3.27)
project(ppe_cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(PPE_WERROR "Treat compiler warnings as errors" ON)
option(PPE_SANITIZE "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(PPE_CLANG_TIDY "Run clang-tidy on the project's sources while building" OFF)
option(PPE_BUILD_TESTS "Build the unit and CLI tests" ON)
set(PPE_CACHE_DIR "${PROJECT_SOURCE_DIR}/.cache" CACHE PATH "Where downloads are kept")

include(cmake/onnxruntime.cmake)
include(cmake/model.cmake)

# Warnings for the project's own code (not for vendored third-party code).
add_library(ppe_warnings INTERFACE)
target_compile_options(ppe_warnings INTERFACE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wold-style-cast
  -Wnon-virtual-dtor -Woverloaded-virtual -Wcast-align -Wnull-dereference
  -Wimplicit-fallthrough -Wformat=2 -Wundef
  $<$<BOOL:${PPE_WERROR}>:-Werror>)

if(PPE_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=all
                      -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=address,undefined)
endif()

if(PPE_CLANG_TIDY)
  find_program(PPE_CLANG_TIDY_EXE NAMES clang-tidy-18 clang-tidy REQUIRED)
  set(CMAKE_CXX_CLANG_TIDY "${PPE_CLANG_TIDY_EXE};--warnings-as-errors=*")
endif()

# stb_image, vendored at a pinned commit (third_party/stb/README.md).
add_library(ppe_stb_image STATIC src/stb_image_impl.cpp)
target_include_directories(ppe_stb_image SYSTEM PUBLIC third_party/stb)
target_include_directories(ppe_stb_image PRIVATE src)
target_compile_options(ppe_stb_image PRIVATE -w)
set_target_properties(ppe_stb_image PROPERTIES SKIP_LINTING ON POSITION_INDEPENDENT_CODE ON)

# The library.
add_library(ppe
  src/error.cpp
  src/image.cpp
  src/preprocess.cpp
  src/postprocess.cpp
  src/json.cpp
  src/detector.cpp)
target_include_directories(ppe PUBLIC include PRIVATE src)
target_link_libraries(ppe PRIVATE onnxruntime::onnxruntime ppe_stb_image ppe_warnings)

# The CLI.
add_executable(ppe_detect tools/ppe_detect.cpp)
target_link_libraries(ppe_detect PRIVATE ppe onnxruntime::onnxruntime ppe_warnings)
target_compile_definitions(ppe_detect PRIVATE
  PPE_VERSION="${PROJECT_VERSION}" PPE_DEFAULT_MODEL="${PPE_MODEL_PATH}")

# The benchmark harness (C++ side; bench/run_bench.py drives it).
add_executable(ppe_bench bench/ppe_bench.cpp)
target_link_libraries(ppe_bench PRIVATE ppe onnxruntime::onnxruntime ppe_warnings)

if(PPE_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()
