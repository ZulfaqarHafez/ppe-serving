// Tests that load the real model. Registered with CTest only when the build
// has the model (see tests/CMakeLists.txt).
#include <doctest.h>

#include <cstddef>
#include <string>
#include <utility>
#include <vector>

#include "ppe/detector.hpp"
#include "ppe/error.hpp"
#include "ppe/image.hpp"

namespace {

std::string model() { return PPE_TEST_MODEL; }
std::string data_dir() { return PPE_TEST_DATA_DIR; }

ppe::ErrorCode load_error(const std::string& path) {
  try {
    const ppe::Detector d(ppe::DetectorOptions{path, 1});
  } catch (const ppe::Error& e) {
    return e.code();
  }
  return ppe::ErrorCode::kInvalidArgument;  // not thrown: the test fails on this
}

}  // namespace

TEST_SUITE("detector") {
  TEST_CASE("the model loads with the expected shapes") {
    REQUIRE_FALSE(model().empty());
    const ppe::Detector d(ppe::DetectorOptions{model(), 1});
    CHECK(d.input_size() == 320);
    CHECK(d.candidate_count() == 2100);
    CHECK(d.input().size() == 3U * 320U * 320U);
    CHECK(d.output().size() == 10U * 2100U);
  }

  TEST_CASE("missing and invalid model files raise kModelLoad") {
    CHECK(load_error(data_dir() + "/no-such-model.onnx") == ppe::ErrorCode::kModelLoad);
    CHECK(load_error(data_dir() + "/reference/samples.json") == ppe::ErrorCode::kModelLoad);
    CHECK(load_error(data_dir()) == ppe::ErrorCode::kModelLoad);
  }

  TEST_CASE("negative thread counts are rejected") {
    try {
      const ppe::Detector d(ppe::DetectorOptions{model(), -1});
      FAIL("no exception");
    } catch (const ppe::Error& e) {
      CHECK(e.code() == ppe::ErrorCode::kInvalidArgument);
    }
  }

  TEST_CASE("detect on a sample finds the reference detections") {
    // samples.json, plant-cctv at 0.25: No-vest 0.694, No-Helmet 0.627.
    ppe::Detector d(ppe::DetectorOptions{model(), 0});
    const ppe::Image image = ppe::load_image(data_dir() + "/samples/plant-cctv.png");
    const auto found = d.detect(image.view(), ppe::DetectParams{});
    REQUIRE(found.size() == 2);
    CHECK(found[0].class_id == 4);
    CHECK(found[0].score == doctest::Approx(0.694).epsilon(0.0008));
    CHECK(found[1].class_id == 2);
    CHECK(found[1].score == doctest::Approx(0.627).epsilon(0.0008));
    for (const auto& det : found) {
      CHECK(det.x1 < det.x2);
      CHECK(det.y1 < det.y2);
      CHECK(det.x2 <= 640.0);
      CHECK(det.y2 <= 640.0);
    }
  }

  TEST_CASE("the stages are deterministic and the detector moves") {
    ppe::Detector a(ppe::DetectorOptions{model(), 1});
    const ppe::Image image = ppe::load_image(data_dir() + "/samples/site-backs.png");
    const auto first = a.detect(image.view(), ppe::DetectParams{});
    const std::vector<float> out1 = a.output();
    ppe::Detector b = std::move(a);
    const auto second = b.detect(image.view(), ppe::DetectParams{});
    CHECK(b.output() == out1);
    REQUIRE(first.size() == second.size());
    for (std::size_t i = 0; i < first.size(); ++i) {
      CHECK(first[i].score == second[i].score);
      CHECK(first[i].x1 == second[i].x1);
    }
  }
}
