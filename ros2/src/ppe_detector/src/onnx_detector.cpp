#include <array>
#include <chrono>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "ppe_detector/onnx_detector.hpp"

namespace ppe_detector
{

namespace
{
double ms_since(std::chrono::steady_clock::time_point t0)
{
  return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}
}  // namespace

OnnxDetector::OnnxDetector(const DetectorOptions & options)
: options_(options),
  env_(ORT_LOGGING_LEVEL_WARNING, "ppe_detector"),
  memory_info_(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault))
{
  Ort::SessionOptions so;
  if (options_.intra_op_threads > 0) {
    so.SetIntraOpNumThreads(options_.intra_op_threads);
  }
  so.SetInterOpNumThreads(1);
  so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
  session_ = std::make_unique<Ort::Session>(env_, options_.model_path.c_str(), so);

  Ort::AllocatorWithDefaultOptions alloc;
  input_name_ = session_->GetInputNameAllocated(0, alloc).get();
  output_name_ = session_->GetOutputNameAllocated(0, alloc).get();
  const auto shape = session_->GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
  if (shape.size() != 3 || (shape[1] > 0 && shape[1] != 4 + kNumClasses)) {
    throw std::runtime_error("unexpected output shape for " + options_.model_path);
  }
}

std::vector<Detection> OnnxDetector::detect(
  const uint8_t * rgb, int width, int height, int stride, double floor, DetectTiming * timing)
{
  const auto t0 = std::chrono::steady_clock::now();
  const int size = options_.input_size;
  const Letterbox box = preprocess_rgb(rgb, width, height, stride, size, tensor_);
  const std::array<int64_t, 4> in_shape{1, 3, size, size};
  Ort::Value input = Ort::Value::CreateTensor<float>(
    memory_info_, tensor_.data(), tensor_.size(), in_shape.data(), in_shape.size());
  const double pre_ms = ms_since(t0);

  const auto t1 = std::chrono::steady_clock::now();
  const char * in_names[] = {input_name_.c_str()};
  const char * out_names[] = {output_name_.c_str()};
  auto outputs = session_->Run(Ort::RunOptions{nullptr}, in_names, &input, 1, out_names, 1);
  const double inf_ms = ms_since(t1);

  const auto t2 = std::chrono::steady_clock::now();
  const auto shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
  const int count = static_cast<int>(shape[2]);
  const float * data = outputs[0].GetTensorData<float>();
  std::vector<Detection> found = decode_candidates(data, count, box, floor);
  if (timing != nullptr) {
    timing->preprocess_ms = pre_ms;
    timing->inference_ms = inf_ms;
    timing->decode_ms = ms_since(t2);
  }
  return found;
}

}  // namespace ppe_detector
