// Run the PPE detector on still images without ROS.
//
//   ppe_detect_image --model M [--threshold 0.25] [--threads 0] [--out DIR] IMAGE...
//
// Prints one JSON object per image with the detections after NMS. With --out,
// writes <DIR>/<stem>_annotated.png.

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "ppe_detector/onnx_detector.hpp"
#include "ppe_detector/ppe_core.hpp"

namespace
{
std::string stem(const std::string & path)
{
  const auto slash = path.find_last_of('/');
  std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
  const auto dot = name.find_last_of('.');
  return dot == std::string::npos ? name : name.substr(0, dot);
}
}  // namespace

int main(int argc, char ** argv)
{
  ppe_detector::DetectorOptions opts;
  double threshold = 0.25;
  std::string out_dir;
  std::vector<std::string> images;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--model" && i + 1 < argc) {
      opts.model_path = argv[++i];
    } else if (a == "--threshold" && i + 1 < argc) {
      threshold = std::atof(argv[++i]);
    } else if (a == "--threads" && i + 1 < argc) {
      opts.intra_op_threads = std::atoi(argv[++i]);
    } else if (a == "--out" && i + 1 < argc) {
      out_dir = argv[++i];
    } else {
      images.push_back(a);
    }
  }
  if (opts.model_path.empty() || images.empty()) {
    std::fprintf(stderr, "usage: %s --model M [--threshold T] [--threads N] [--out DIR] IMAGE...\n",
      argv[0]);
    return 2;
  }
  ppe_detector::OnnxDetector detector(opts);
  for (const auto & path : images) {
    cv::Mat bgr = cv::imread(path, cv::IMREAD_COLOR);
    if (bgr.empty()) {
      std::fprintf(stderr, "cannot read %s\n", path.c_str());
      return 1;
    }
    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    ppe_detector::DetectTiming t;
    const auto kept = ppe_detector::select_detections(
      detector.detect(rgb.data, rgb.cols, rgb.rows, static_cast<int>(rgb.step), 0.05, &t),
      threshold);
    std::printf("{\"image\": \"%s\", \"inference_ms\": %.2f, \"detections\": [", stem(path).c_str(),
      t.inference_ms);
    for (size_t k = 0; k < kept.size(); ++k) {
      const auto & d = kept[k];
      std::printf("%s{\"label\": \"%s\", \"score\": %.4f, \"box\": [%.1f, %.1f, %.1f, %.1f]}",
        k ? ", " : "", ppe_detector::kClassNames[d.class_id], d.score, d.x1, d.y1, d.x2, d.y2);
      const bool missing = ppe_detector::is_missing_item(ppe_detector::kClassNames[d.class_id]);
      const cv::Scalar colour = missing ? cv::Scalar(43, 58, 166) : cv::Scalar(50, 125, 46);
      cv::rectangle(bgr, cv::Point(d.x1, d.y1), cv::Point(d.x2, d.y2), colour, 2);
      char text[64];
      std::snprintf(text, sizeof(text), "%s %.2f", ppe_detector::kClassNames[d.class_id], d.score);
      cv::putText(bgr, text, cv::Point(d.x1 + 2, std::max(12.0, d.y1 - 4)),
        cv::FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv::LINE_AA);
    }
    std::printf("]}\n");
    if (!out_dir.empty()) {
      cv::imwrite(out_dir + "/" + stem(path) + "_annotated.png", bgr);
    }
  }
  return 0;
}
