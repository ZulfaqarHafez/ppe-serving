#include "ppe/error.hpp"

#include <string>

namespace ppe {

const char* to_string(ErrorCode code) noexcept {
  switch (code) {
    case ErrorCode::kInvalidArgument:
      return "invalid_argument";
    case ErrorCode::kImageRead:
      return "image_read";
    case ErrorCode::kModelLoad:
      return "model_load";
    case ErrorCode::kInference:
      return "inference";
    case ErrorCode::kIo:
      return "io";
  }
  return "unknown";
}

Error::Error(ErrorCode code, const std::string& message)
    : std::runtime_error(message), code_(code) {}

}  // namespace ppe
