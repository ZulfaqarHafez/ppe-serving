// ppe_detect: run the PPE detector on image files and print JSON.
//
// Exit codes (also in --help and the README):
//   0 success            3 an image could not be read or decoded
//   1 unexpected error   4 the model could not be loaded or has the wrong shape
//   2 usage error        5 inference failed
//                        6 writing a --dump-dir file failed

#include <onnxruntime_cxx_api.h>

#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "ppe/detector.hpp"
#include "ppe/error.hpp"
#include "ppe/image.hpp"
#include "ppe/json.hpp"
#include "ppe/postprocess.hpp"

#ifndef PPE_DEFAULT_MODEL
#define PPE_DEFAULT_MODEL ""
#endif
#ifndef PPE_VERSION
#define PPE_VERSION "0.0.0"
#endif

namespace {

enum ExitCode : int {
  kOk = 0,
  kUnexpected = 1,
  kUsage = 2,
  kImage = 3,
  kModel = 4,
  kInfer = 5,
  kIoFail = 6,
};

constexpr std::string_view kUsageText =
    R"(Usage: ppe_detect [options] IMAGE [IMAGE...]

Detects PPE (Gloves, Helmet, No-Helmet, No-gloves, No-vest, Vest) in PNG, JPEG
or BMP images and prints one JSON document to stdout.

Options:
  --model PATH       ONNX model (default: the model the build downloaded)
  --threshold T      minimum class score, 0 to 1 (default 0.25)
  --iou I            per-class NMS IoU limit, 0 to 1 (default 0.7)
  --threads N        ONNX Runtime intra-op threads, 0 = runtime default (default 0)
  --dump-dir DIR     also write each image's input tensor and raw output as
                     little-endian float32 files <stem>.input.f32, <stem>.output.f32
  --help             show this text and exit
  --version          show the version and exit

Exit codes: 0 success, 1 unexpected error, 2 usage error, 3 image unreadable,
4 model unusable, 5 inference failed, 6 writing a dump file failed.
)";

struct Options {
  std::string model{PPE_DEFAULT_MODEL};
  ppe::DetectParams params;
  int threads{0};
  std::string dump_dir;
  std::vector<std::string> images;
};

struct UsageError {
  std::string message;
};

std::optional<double> parse_double(std::string_view text) {
  double value = 0.0;
  const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
  if (ec != std::errc{} || end != text.data() + text.size()) {
    return std::nullopt;
  }
  return value;
}

std::optional<int> parse_int(std::string_view text) {
  int value = 0;
  const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
  if (ec != std::errc{} || end != text.data() + text.size()) {
    return std::nullopt;
  }
  return value;
}

double unit_interval(std::string_view flag, std::string_view text) {
  const auto v = parse_double(text);
  if (!v || !(*v >= 0.0 && *v <= 1.0)) {
    throw UsageError{std::string(flag) + " needs a number from 0 to 1, got '" +
                     std::string(text) + "'"};
  }
  return *v;
}

// Returns nullopt when --help or --version was handled.
std::optional<Options> parse_args(const std::vector<std::string_view>& args) {
  Options o;
  for (std::size_t i = 0; i < args.size(); ++i) {
    const std::string_view a = args[i];
    const auto value = [&]() -> std::string_view {
      if (i + 1 >= args.size()) {
        throw UsageError{std::string(a) + " needs a value"};
      }
      return args[++i];
    };
    if (a == "--help" || a == "-h") {
      std::cout << kUsageText;
      return std::nullopt;
    }
    if (a == "--version") {
      std::cout << "ppe_detect " << PPE_VERSION << " (onnxruntime " << Ort::GetVersionString()
                << ")\n";
      return std::nullopt;
    }
    if (a == "--model") {
      o.model = value();
    } else if (a == "--threshold") {
      o.params.score_threshold = unit_interval(a, value());
    } else if (a == "--iou") {
      o.params.iou_threshold = unit_interval(a, value());
    } else if (a == "--threads") {
      const std::string_view text = value();
      const auto n = parse_int(text);
      if (!n || *n < 0 || *n > 256) {
        throw UsageError{"--threads needs a whole number from 0 to 256, got '" +
                         std::string(text) + "'"};
      }
      o.threads = *n;
    } else if (a == "--dump-dir") {
      o.dump_dir = value();
    } else if (a.size() > 1 && a.front() == '-') {
      throw UsageError{"unknown option " + std::string(a)};
    } else {
      o.images.emplace_back(a);
    }
  }
  if (o.images.empty()) {
    throw UsageError{"no image given"};
  }
  if (o.model.empty()) {
    throw UsageError{"no model: pass --model PATH"};
  }
  return o;
}

void write_floats(const std::filesystem::path& path, const std::vector<float>& data) {
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): raw bytes out
  f.write(reinterpret_cast<const char*>(data.data()),
          static_cast<std::streamsize>(data.size() * sizeof(float)));
  if (!f) {
    throw ppe::Error(ppe::ErrorCode::kIo, "cannot write " + path.string());
  }
}

int exit_code_for(ppe::ErrorCode code) {
  switch (code) {
    case ppe::ErrorCode::kInvalidArgument:
      return kUsage;
    case ppe::ErrorCode::kImageRead:
      return kImage;
    case ppe::ErrorCode::kModelLoad:
      return kModel;
    case ppe::ErrorCode::kInference:
      return kInfer;
    case ppe::ErrorCode::kIo:
      return kIoFail;
  }
  return kUnexpected;
}

int run(const Options& o) {
  ppe::Detector detector(ppe::DetectorOptions{o.model, o.threads});
  if (!o.dump_dir.empty()) {
    std::error_code ec;
    std::filesystem::create_directories(o.dump_dir, ec);
    if (ec) {
      throw ppe::Error(ppe::ErrorCode::kIo, "cannot create " + o.dump_dir + ": " + ec.message());
    }
  }
  std::string out = "{\"model\":" +
                    ppe::json_string(std::filesystem::path(o.model).filename().string()) +
                    ",\"input_size\":" + std::to_string(detector.input_size()) +
                    ",\"threads\":" + std::to_string(o.threads) +
                    ",\"score_threshold\":" + ppe::json_number(o.params.score_threshold) +
                    ",\"iou_threshold\":" + ppe::json_number(o.params.iou_threshold) +
                    ",\"images\":[";
  bool first = true;
  for (const std::string& path : o.images) {
    const ppe::Image image = ppe::load_image(path);
    ppe::ImageResult result{path, image.width(), image.height(), {}};
    result.detections = detector.detect(image.view(), o.params);
    if (!o.dump_dir.empty()) {
      const std::filesystem::path stem = std::filesystem::path(path).stem();
      const std::filesystem::path dir(o.dump_dir);
      write_floats(dir / (stem.string() + ".input.f32"), detector.input());
      write_floats(dir / (stem.string() + ".output.f32"), detector.output());
    }
    out += (first ? "" : ",") + ppe::image_result_to_json(result);
    first = false;
  }
  out += "]}\n";
  std::cout << out << std::flush;
  return kOk;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::vector<std::string_view> args(argv + 1, argv + argc);
    const std::optional<Options> options = parse_args(args);
    if (!options) {
      return kOk;
    }
    return run(*options);
  } catch (const UsageError& e) {
    std::cerr << "ppe_detect: " << e.message << "\nTry 'ppe_detect --help'.\n";
    return kUsage;
  } catch (const ppe::Error& e) {
    std::cerr << "ppe_detect: error (" << ppe::to_string(e.code()) << "): " << e.what() << "\n";
    return exit_code_for(e.code());
  } catch (const std::exception& e) {
    std::cerr << "ppe_detect: unexpected error: " << e.what() << "\n";
    return kUnexpected;
  }
}
