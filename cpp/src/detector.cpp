#include "ppe/detector.hpp"

#include <onnxruntime_cxx_api.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include "ppe/error.hpp"
#include "ppe/image.hpp"
#include "ppe/postprocess.hpp"
#include "ppe/preprocess.hpp"

namespace ppe {

struct Detector::Impl {
  // Declaration order is destruction order in reverse: the session must go
  // before the environment it was created in.
  Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "ppe"};
  Ort::Session session{nullptr};
  Ort::MemoryInfo memory{Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)};
  std::string input_name;
  std::string output_name;
  int size{0};
  std::size_t count{0};
  std::array<std::int64_t, 4> input_shape{};
  std::array<std::int64_t, 3> output_shape{};
  std::vector<float> input;
  std::vector<float> output;
};

namespace {

[[noreturn]] void bad_model(const std::string& path, const std::string& why) {
  throw Error(ErrorCode::kModelLoad, "model " + path + ": " + why);
}

}  // namespace

Detector::Detector(const DetectorOptions& options) : impl_(std::make_unique<Impl>()) {
  const std::string& path = options.model_path;
  std::error_code ec;
  if (!std::filesystem::is_regular_file(path, ec)) {
    bad_model(path, "no such file");
  }
  if (options.threads < 0) {
    throw Error(ErrorCode::kInvalidArgument, "threads must be 0 (default) or positive");
  }
  try {
    Ort::SessionOptions so;
    so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    if (options.threads > 0) {
      so.SetIntraOpNumThreads(options.threads);
      so.SetInterOpNumThreads(1);
    }
    impl_->session = Ort::Session(impl_->env, path.c_str(), so);

    const Ort::Session& s = impl_->session;
    if (s.GetInputCount() != 1 || s.GetOutputCount() != 1) {
      bad_model(path, "expected one input and one output");
    }
    const Ort::AllocatorWithDefaultOptions alloc;
    impl_->input_name = s.GetInputNameAllocated(0, alloc).get();
    impl_->output_name = s.GetOutputNameAllocated(0, alloc).get();

    // The shape infos are views into the TypeInfo objects, so keep those alive.
    const Ort::TypeInfo in_type = s.GetInputTypeInfo(0);
    const auto in_info = in_type.GetTensorTypeAndShapeInfo();
    const auto in = in_info.GetShape();
    if (in_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT || in.size() != 4 ||
        in[0] != 1 || in[1] != 3 || in[2] <= 0 || in[2] != in[3] || in[2] > kMaxImageSide) {
      bad_model(path, "input must be float [1, 3, S, S] with a static S");
    }
    const Ort::TypeInfo out_type = s.GetOutputTypeInfo(0);
    const auto out_info = out_type.GetTensorTypeAndShapeInfo();
    const auto out = out_info.GetShape();
    if (out_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT || out.size() != 3 ||
        out[0] != 1 || out[1] != kOutputRows || out[2] <= 0) {
      bad_model(path,
                "output must be float [1, " + std::to_string(kOutputRows) + ", N] with a static N");
    }
    impl_->size = static_cast<int>(in[2]);
    impl_->count = static_cast<std::size_t>(out[2]);
    impl_->input_shape = {1, 3, in[2], in[2]};
    impl_->output_shape = {1, kOutputRows, out[2]};
    const auto side = static_cast<std::size_t>(impl_->size);
    impl_->input.assign(3 * side * side, 0.0F);
    impl_->output.assign(static_cast<std::size_t>(kOutputRows) * impl_->count, 0.0F);
  } catch (const Ort::Exception& e) {
    bad_model(path, e.what());
  }
}

Detector::~Detector() = default;
Detector::Detector(Detector&&) noexcept = default;
Detector& Detector::operator=(Detector&&) noexcept = default;

int Detector::input_size() const noexcept { return impl_->size; }

std::size_t Detector::candidate_count() const noexcept { return impl_->count; }

Letterbox Detector::set_input(const ImageView& image) {
  return preprocess(image, impl_->size, impl_->input);
}

void Detector::run() {
  Impl& m = *impl_;
  try {
    // The tensors wrap the buffers this object owns: no copy in or out.
    const Ort::Value in = Ort::Value::CreateTensor<float>(
        m.memory, m.input.data(), m.input.size(), m.input_shape.data(), m.input_shape.size());
    Ort::Value out = Ort::Value::CreateTensor<float>(m.memory, m.output.data(), m.output.size(),
                                                     m.output_shape.data(), m.output_shape.size());
    const std::array<const char*, 1> in_names{m.input_name.c_str()};
    const std::array<const char*, 1> out_names{m.output_name.c_str()};
    m.session.Run(Ort::RunOptions{nullptr}, in_names.data(), &in, 1, out_names.data(), &out, 1);
  } catch (const Ort::Exception& e) {
    throw Error(ErrorCode::kInference, std::string("inference failed: ") + e.what());
  }
}

std::vector<Detection> Detector::decode(const Letterbox& box, const DetectParams& params) const {
  return postprocess(impl_->output.data(), impl_->count, box, params);
}

std::vector<Detection> Detector::detect(const ImageView& image, const DetectParams& params) {
  const Letterbox box = set_input(image);
  run();
  return decode(box, params);
}

const std::vector<float>& Detector::input() const noexcept { return impl_->input; }

const std::vector<float>& Detector::output() const noexcept { return impl_->output; }

}  // namespace ppe
