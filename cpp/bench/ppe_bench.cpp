// ppe_bench: time each stage of the C++ pipeline and print the raw samples as
// JSON. bench/run_bench.py runs this alternately with bench/bench_py.py and
// computes the statistics; this program only measures.
//
// Usage: ppe_bench --model PATH --threads N --warmup W --iterations K IMAGE...
// Iteration i uses IMAGE[i % count]. Warm-up iterations are run the same way
// and not recorded. Stages, each timed with steady_clock:
//   decode       read the file and decode it to RGB8
//   preprocess   letterbox resize and the float tensor
//   inference    Session::Run
//   postprocess  decode candidates and per-class NMS
//   end_to_end   all four, timed as one span

#include <onnxruntime_cxx_api.h>

#include <charconv>
#include <chrono>
#include <cstddef>
#include <exception>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "ppe/detector.hpp"
#include "ppe/error.hpp"
#include "ppe/image.hpp"
#include "ppe/json.hpp"
#include "ppe/postprocess.hpp"

namespace {

using Clock = std::chrono::steady_clock;

double ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double, std::milli>(b - a).count();
}

int to_int(std::string_view text) {
  int v = 0;
  const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), v);
  if (ec != std::errc{} || end != text.data() + text.size() || v < 0) {
    throw ppe::Error(ppe::ErrorCode::kInvalidArgument, "bad number " + std::string(text));
  }
  return v;
}

std::string series(const std::vector<double>& values) {
  std::string out = "[";
  for (std::size_t i = 0; i < values.size(); ++i) {
    out += (i > 0 ? "," : "") + ppe::json_number(values[i]);
  }
  return out + "]";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::vector<std::string_view> args(argv + 1, argv + argc);
    std::string model;
    int threads = 0;
    int warmup = 20;
    int iterations = 100;
    std::vector<std::string> images;
    for (std::size_t i = 0; i < args.size(); ++i) {
      const std::string_view a = args[i];
      const bool has_value = i + 1 < args.size();
      if (a == "--model" && has_value) {
        model = args[++i];
      } else if (a == "--threads" && has_value) {
        threads = to_int(args[++i]);
      } else if (a == "--warmup" && has_value) {
        warmup = to_int(args[++i]);
      } else if (a == "--iterations" && has_value) {
        iterations = to_int(args[++i]);
      } else if (!a.empty() && a.front() != '-') {
        images.emplace_back(a);
      } else {
        std::cerr << "ppe_bench: bad argument " << a << "\n";
        return 2;
      }
    }
    if (model.empty() || images.empty() || iterations <= 0) {
      std::cerr << "usage: ppe_bench --model PATH [--threads N] [--warmup W] "
                   "[--iterations K] IMAGE...\n";
      return 2;
    }

    ppe::Detector detector(ppe::DetectorOptions{model, threads});
    const ppe::DetectParams params;  // 0.25 and 0.7, the CLI defaults
    const auto total = static_cast<std::size_t>(warmup + iterations);
    const auto keep = static_cast<std::size_t>(iterations);
    std::vector<double> t_decode;
    std::vector<double> t_pre;
    std::vector<double> t_infer;
    std::vector<double> t_post;
    std::vector<double> t_e2e;
    for (auto* v : {&t_decode, &t_pre, &t_infer, &t_post, &t_e2e}) {
      v->reserve(keep);
    }
    std::size_t detections = 0;
    for (std::size_t i = 0; i < total; ++i) {
      const std::string& path = images[i % images.size()];
      const auto t0 = Clock::now();
      const ppe::Image image = ppe::load_image(path);
      const auto t1 = Clock::now();
      const ppe::Letterbox box = detector.set_input(image.view());
      const auto t2 = Clock::now();
      detector.run();
      const auto t3 = Clock::now();
      const std::vector<ppe::Detection> found = detector.decode(box, params);
      const auto t4 = Clock::now();
      if (i < static_cast<std::size_t>(warmup)) {
        continue;
      }
      detections += found.size();
      t_decode.push_back(ms(t0, t1));
      t_pre.push_back(ms(t1, t2));
      t_infer.push_back(ms(t2, t3));
      t_post.push_back(ms(t3, t4));
      t_e2e.push_back(ms(t0, t4));
    }
    std::cout << "{\"language\":\"cpp\",\"onnxruntime\":" +
                     ppe::json_string(Ort::GetVersionString()) +
                     ",\"threads\":" + std::to_string(threads) +
                     ",\"warmup\":" + std::to_string(warmup) +
                     ",\"iterations\":" + std::to_string(iterations) +
                     ",\"detections\":" + std::to_string(detections) +
                     ",\"stages_ms\":{\"decode\":" + series(t_decode) +
                     ",\"preprocess\":" + series(t_pre) + ",\"inference\":" + series(t_infer) +
                     ",\"postprocess\":" + series(t_post) + ",\"end_to_end\":" + series(t_e2e) +
                     "}}\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "ppe_bench: " << e.what() << "\n";
    return 1;
  }
}
