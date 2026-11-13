// Parity: the C++ pipeline on the five sample images must find what the site's
// reference run found (samples.json, made by scripts/ppe-samples.py with Pillow
// and onnxruntime in Python): the same labels at thresholds 0.25 and 0.5, each
// score within kScoreTolerance.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "ppe_detector/onnx_detector.hpp"
#include "ppe_detector/ppe_core.hpp"

namespace
{
// samples.json rounds scores to 3 decimals, so 0.0005 is the rounding alone.
constexpr double kScoreTolerance = 0.001;

using Expected = std::map<std::string, std::vector<std::pair<std::string, double>>>;

// Minimal reader for the fixed layout of samples.json: per sample id, the
// detections (label, score) at each threshold.
std::map<std::string, Expected> read_samples(const std::string & path)
{
  std::ifstream f(path);
  std::stringstream ss;
  ss << f.rdbuf();
  const std::string text = ss.str();
  std::map<std::string, Expected> out;
  const std::regex id_re("\"id\":\\s*\"([^\"]+)\"");
  const std::regex det_re("\"label\":\\s*\"([^\"]+)\",\\s*\"score\":\\s*([0-9.]+)");
  std::vector<std::pair<size_t, std::string>> ids;
  for (auto it = std::sregex_iterator(text.begin(), text.end(), id_re);
    it != std::sregex_iterator(); ++it)
  {
    ids.emplace_back(it->position(0), (*it)[1]);
  }
  for (size_t i = 0; i < ids.size(); ++i) {
    const size_t end = i + 1 < ids.size() ? ids[i + 1].first : text.size();
    const std::string seg = text.substr(ids[i].first, end - ids[i].first);
    for (const std::string thr : {"0.25", "0.5"}) {
      const size_t at = seg.find("\"" + thr + "\": {");
      const size_t open = seg.find("\"detections\":", at);
      const size_t close = seg.find(']', open);
      const std::string list = seg.substr(open, close - open);
      auto & v = out[ids[i].second][thr];
      for (auto it = std::sregex_iterator(list.begin(), list.end(), det_re);
        it != std::sregex_iterator(); ++it)
      {
        v.emplace_back((*it)[1], std::stod((*it)[2]));
      }
    }
  }
  return out;
}

// Pair each expected detection with an unused found one of the same label and
// the closest score; return a description of the first mismatch, or "".
std::string compare(
  std::vector<std::pair<std::string, double>> expected,
  std::vector<std::pair<std::string, double>> found, double * worst)
{
  if (expected.size() != found.size()) {
    return "expected " + std::to_string(expected.size()) + " detections, found " +
           std::to_string(found.size());
  }
  std::vector<bool> used(found.size(), false);
  for (const auto & e : expected) {
    int best = -1;
    for (size_t j = 0; j < found.size(); ++j) {
      if (!used[j] && found[j].first == e.first &&
        (best < 0 || std::abs(found[j].second - e.second) <
        std::abs(found[best].second - e.second)))
      {
        best = static_cast<int>(j);
      }
    }
    if (best < 0) {
      return "no " + e.first + " found";
    }
    used[best] = true;
    const double diff = std::abs(found[best].second - e.second);
    *worst = std::max(*worst, diff);
    if (diff > kScoreTolerance) {
      return e.first + " score " + std::to_string(found[best].second) + " vs " +
             std::to_string(e.second);
    }
  }
  return "";
}
}  // namespace

TEST(Parity, MatchesSamplesJson)
{
  const std::string dir = PPE_SAMPLES_DIR;
  const auto expected = read_samples(dir + "/samples.json");
  ASSERT_EQ(expected.size(), 5u);
  ppe_detector::DetectorOptions opts;
  opts.model_path = PPE_MODEL;
  ppe_detector::OnnxDetector detector(opts);
  double worst = 0.0;
  int compared = 0;
  for (const auto & [id, by_thr] : expected) {
    cv::Mat bgr = cv::imread(dir + "/" + id + ".png", cv::IMREAD_COLOR);
    ASSERT_FALSE(bgr.empty()) << id;
    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    const auto cands = detector.detect(
      rgb.data, rgb.cols, rgb.rows, static_cast<int>(rgb.step), 0.05);
    for (const auto & [thr, exp] : by_thr) {
      std::vector<std::pair<std::string, double>> found;
      for (const auto & d : ppe_detector::select_detections(cands, std::stod(thr))) {
        found.emplace_back(ppe_detector::kClassNames[d.class_id], d.score);
      }
      const std::string err = compare(exp, found, &worst);
      EXPECT_EQ(err, "") << id << " at " << thr;
      compared += static_cast<int>(exp.size());
    }
  }
  std::printf("parity: %d expected detections compared, worst score difference %.4f\n",
    compared, worst);
}
