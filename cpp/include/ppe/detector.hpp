// The detector: one ONNX Runtime session plus the input and output buffers it
// runs on. ONNX Runtime types stay out of this header (pimpl).

#ifndef PPE_DETECTOR_HPP
#define PPE_DETECTOR_HPP

#include <memory>
#include <string>
#include <vector>

#include "ppe/image.hpp"
#include "ppe/postprocess.hpp"
#include "ppe/preprocess.hpp"

namespace ppe {

struct DetectorOptions {
  std::string model_path;
  /// ONNX Runtime threads. 0 leaves both intra- and inter-op pools at the
  /// runtime default; N > 0 sets intra-op to N and inter-op to 1.
  int threads{0};
};

/// Owns the ONNX Runtime environment and session and the input and output
/// tensors' memory. Move-only. Not thread-safe: use one per thread.
class Detector {
 public:
  /// Loads and checks the model. Throws Error(kModelLoad) if the file is
  /// missing or invalid or its input is not float [1, 3, S, S] or its output
  /// is not float [1, 4 + classes, N] with static sizes.
  explicit Detector(const DetectorOptions& options);
  ~Detector();
  Detector(Detector&&) noexcept;
  Detector& operator=(Detector&&) noexcept;
  Detector(const Detector&) = delete;
  Detector& operator=(const Detector&) = delete;

  /// Side of the square input (320 for the shipped model).
  [[nodiscard]] int input_size() const noexcept;
  /// Number of candidate columns in the output (2100 at 320).
  [[nodiscard]] std::size_t candidate_count() const noexcept;

  // The three stages, exposed separately for timing and parity checks.

  /// Letterbox `image` into the input tensor.
  Letterbox set_input(const ImageView& image);
  /// Run the model on the current input tensor into the output buffer.
  /// Throws Error(kInference) on failure.
  void run();
  /// Decode and NMS the current output.
  [[nodiscard]] std::vector<Detection> decode(const Letterbox& box,
                                              const DetectParams& params) const;

  /// All three stages.
  std::vector<Detection> detect(const ImageView& image, const DetectParams& params);

  /// The input tensor, [3, S, S] planar.
  [[nodiscard]] const std::vector<float>& input() const noexcept;
  /// The raw output, [4 + classes, N] row-major.
  [[nodiscard]] const std::vector<float>& output() const noexcept;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace ppe

#endif  // PPE_DETECTOR_HPP
