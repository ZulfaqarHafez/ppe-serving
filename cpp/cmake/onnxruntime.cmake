# ONNX Runtime: the official prebuilt Linux x64 release from GitHub, pinned by
# version and SHA-256, downloaded once into PPE_CACHE_DIR. Set PPE_ORT_ROOT to
# use an already extracted copy of the same release instead.

set(PPE_ORT_VERSION "1.29.0")
set(PPE_ORT_SHA256 "c3fddc4f139a045b0c4902c57410f0694f1c2fdf9b6939fbe38b1aeae7cd14ba")
set(PPE_ORT_NAME "onnxruntime-linux-x64-${PPE_ORT_VERSION}")
set(PPE_ORT_URL
    "https://github.com/microsoft/onnxruntime/releases/download/v${PPE_ORT_VERSION}/${PPE_ORT_NAME}.tgz")
set(PPE_ORT_ROOT "" CACHE PATH "Extracted ${PPE_ORT_NAME} (optional; downloaded if empty)")

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64)$")
  message(FATAL_ERROR "Only Linux x86_64 is supported (the pinned ONNX Runtime build is linux-x64)")
endif()

if(NOT PPE_ORT_ROOT)
  set(PPE_ORT_ROOT "${PPE_CACHE_DIR}/${PPE_ORT_NAME}")
  set(_archive "${PPE_CACHE_DIR}/${PPE_ORT_NAME}.tgz")
  set(_hash "")
  if(NOT EXISTS "${PPE_ORT_ROOT}/lib/libonnxruntime.so.${PPE_ORT_VERSION}")
    if(EXISTS "${_archive}")
      file(SHA256 "${_archive}" _hash)
    endif()
    if(NOT _hash STREQUAL PPE_ORT_SHA256)
      message(STATUS "Downloading ${PPE_ORT_URL}")
      file(DOWNLOAD "${PPE_ORT_URL}" "${_archive}.part"
           EXPECTED_HASH SHA256=${PPE_ORT_SHA256} TLS_VERIFY ON STATUS _status)
      list(GET _status 0 _code)
      if(NOT _code EQUAL 0)
        file(REMOVE "${_archive}.part")
        message(FATAL_ERROR "Download of ${PPE_ORT_URL} failed: ${_status}")
      endif()
      file(RENAME "${_archive}.part" "${_archive}")
    endif()
    file(ARCHIVE_EXTRACT INPUT "${_archive}" DESTINATION "${PPE_CACHE_DIR}")
  endif()
endif()

set(_ort_lib "${PPE_ORT_ROOT}/lib/libonnxruntime.so.${PPE_ORT_VERSION}")
if(NOT EXISTS "${_ort_lib}" OR NOT EXISTS "${PPE_ORT_ROOT}/include/onnxruntime_cxx_api.h")
  message(FATAL_ERROR "No ONNX Runtime ${PPE_ORT_VERSION} at ${PPE_ORT_ROOT}")
endif()

add_library(onnxruntime::onnxruntime SHARED IMPORTED GLOBAL)
set_target_properties(onnxruntime::onnxruntime PROPERTIES
  IMPORTED_LOCATION "${_ort_lib}"
  IMPORTED_SONAME "libonnxruntime.so.1"
  INTERFACE_SYSTEM_INCLUDE_DIRECTORIES "${PPE_ORT_ROOT}/include"
  INTERFACE_INCLUDE_DIRECTORIES "${PPE_ORT_ROOT}/include")
