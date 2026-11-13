// The one error type of the library. Every failure the library can report is a
// ppe::Error carrying an ErrorCode; the CLI maps the code to its exit status.

#ifndef PPE_ERROR_HPP
#define PPE_ERROR_HPP

#include <stdexcept>
#include <string>

namespace ppe {

enum class ErrorCode {
  kInvalidArgument,  // a caller passed a value the library cannot use
  kImageRead,        // an image file is missing, unreadable or not a decodable image
  kModelLoad,        // the model file is missing, invalid, or has an unexpected shape
  kInference,        // ONNX Runtime failed while running the model
  kIo,               // writing an output file failed
};

/// Short stable name of a code, used in messages ("image_read").
const char* to_string(ErrorCode code) noexcept;

class Error : public std::runtime_error {
 public:
  Error(ErrorCode code, const std::string& message);

  [[nodiscard]] ErrorCode code() const noexcept { return code_; }

 private:
  ErrorCode code_;
};

}  // namespace ppe

#endif  // PPE_ERROR_HPP
