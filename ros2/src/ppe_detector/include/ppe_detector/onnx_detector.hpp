// Thin wrapper around an ONNX Runtime session for the PPE detector.

#ifndef PPE_DETECTOR__ONNX_DETECTOR_HPP_
#define PPE_DETECTOR__ONNX_DETECTOR_HPP_

#include <onnxruntime_cxx_api.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "ppe_detector/ppe_core.hpp"

namespace ppe_detector
{

struct DetectorOptions
{
  std::string model_path;
  int input_size{320};
  /// ONNX Runtime intra-op threads; 0 keeps the runtime default.
  int intra_op_threads{0};
};

/// Wall-clock split of one call to OnnxDetector::detect, in milliseconds.
struct DetectTiming
{
  double preprocess_ms{0.0};
  double inference_ms{0.0};
  double decode_ms{0.0};
};

class OnnxDetector
{
public:
  explicit OnnxDetector(const DetectorOptions & options);

  /// Run the model on an interleaved RGB8 image and return every candidate
  /// whose best class score is at least `floor` (before NMS).
  std::vector<Detection> detect(
    const uint8_t * rgb, int width, int height, int stride, double floor,
    DetectTiming * timing = nullptr);

  int input_size() const {return options_.input_size;}

private:
  DetectorOptions options_;
  Ort::Env env_;
  std::unique_ptr<Ort::Session> session_;
  Ort::MemoryInfo memory_info_;
  std::vector<float> tensor_;
  std::string input_name_;
  std::string output_name_;
};

}  // namespace ppe_detector

#endif  // PPE_DETECTOR__ONNX_DETECTOR_HPP_
