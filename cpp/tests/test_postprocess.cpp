#include <doctest.h>

#include <cstddef>
#include <vector>

#include "ppe/postprocess.hpp"
#include "ppe/preprocess.hpp"

namespace {

// A fake output0 block with `count` candidates, all scores 0.
struct FakeOutput {
  explicit FakeOutput(std::size_t n) : count(n), data(ppe::kOutputRows * n, 0.0F) {}
  void set(std::size_t j, float cx, float cy, float w, float h, int cls, float score) {
    data[0 * count + j] = cx;
    data[1 * count + j] = cy;
    data[2 * count + j] = w;
    data[3 * count + j] = h;
    data[(4 + static_cast<std::size_t>(cls)) * count + j] = score;
  }
  std::size_t count;
  std::vector<float> data;
};

ppe::Detection box(int cls, double score, double x1, double y1, double x2, double y2) {
  return ppe::Detection{cls, score, x1, y1, x2, y2};
}

}  // namespace

TEST_SUITE("postprocess") {
  TEST_CASE("decode maps letterboxed boxes back to image pixels") {
    // 640x486 image into 320: ratio 0.5, pad_y 38.
    const ppe::Letterbox lb = ppe::compute_letterbox(640, 486, 320);
    FakeOutput out(3);
    out.set(0, 100.0F, 138.0F, 40.0F, 20.0F, 5, 0.9F);
    out.set(1, 50.0F, 50.0F, 10.0F, 10.0F, 1, 0.1F);  // below the floor
    const auto found = ppe::decode_candidates(out.data.data(), out.count, lb, 0.25);
    REQUIRE(found.size() == 1);
    CHECK(found[0].class_id == 5);
    CHECK(found[0].score == doctest::Approx(0.9));
    CHECK(found[0].x1 == doctest::Approx(160.0));  // (100 - 20 - 0) / 0.5
    CHECK(found[0].y1 == doctest::Approx(180.0));  // (138 - 10 - 38) / 0.5
    CHECK(found[0].x2 == doctest::Approx(240.0));
    CHECK(found[0].y2 == doctest::Approx(220.0));
  }

  TEST_CASE("decode takes the best class and keeps the lower index on ties") {
    const ppe::Letterbox lb = ppe::compute_letterbox(320, 320, 320);
    FakeOutput out(2);
    out.set(0, 10.0F, 10.0F, 4.0F, 4.0F, 2, 0.6F);
    out.data[(4 + 4) * out.count + 0] = 0.7F;  // class 4 beats class 2
    out.set(1, 10.0F, 10.0F, 4.0F, 4.0F, 1, 0.5F);
    out.data[(4 + 3) * out.count + 1] = 0.5F;  // tie between 1 and 3
    const auto found = ppe::decode_candidates(out.data.data(), out.count, lb, 0.0);
    REQUIRE(found.size() == 2);
    CHECK(found[0].class_id == 4);
    CHECK(found[1].class_id == 1);
  }

  TEST_CASE("decode clamps boxes to the image") {
    const ppe::Letterbox lb = ppe::compute_letterbox(640, 360, 320);  // pad_y 70
    FakeOutput out(1);
    out.set(0, 5.0F, 75.0F, 30.0F, 30.0F, 0, 0.8F);
    const auto found = ppe::decode_candidates(out.data.data(), out.count, lb, 0.25);
    REQUIRE(found.size() == 1);
    CHECK(found[0].x1 == 0.0);
    CHECK(found[0].y1 == 0.0);
    CHECK(found[0].x2 == doctest::Approx(40.0));
    CHECK(found[0].y2 == doctest::Approx(40.0));
    out.set(0, 318.0F, 250.0F, 30.0F, 30.0F, 0, 0.8F);
    const auto edge = ppe::decode_candidates(out.data.data(), out.count, lb, 0.25);
    CHECK(edge[0].x2 == doctest::Approx(640.0));
    CHECK(edge[0].y2 == doctest::Approx(360.0));
  }

  TEST_CASE("the floor is inclusive") {
    const ppe::Letterbox lb = ppe::compute_letterbox(320, 320, 320);
    FakeOutput out(1);
    out.set(0, 10.0F, 10.0F, 4.0F, 4.0F, 0, 0.5F);
    CHECK(ppe::decode_candidates(out.data.data(), 1, lb, 0.5).size() == 1);
    CHECK(ppe::decode_candidates(out.data.data(), 1, lb, 0.50001).empty());
  }

  TEST_CASE("iou") {
    const auto a = box(0, 1, 0, 0, 10, 10);
    CHECK(ppe::iou(a, a) == doctest::Approx(1.0));
    CHECK(ppe::iou(a, box(0, 1, 5, 0, 15, 10)) == doctest::Approx(50.0 / 150.0));
    CHECK(ppe::iou(a, box(0, 1, 20, 20, 30, 30)) == 0.0);
    CHECK(ppe::iou(box(0, 1, 3, 3, 3, 3), box(0, 1, 3, 3, 3, 3)) == 0.0);  // empty union
  }

  TEST_CASE("NMS suppresses overlaps within a class only") {
    std::vector<ppe::Detection> c{
        box(1, 0.6, 0, 0, 10, 10),
        box(1, 0.9, 1, 0, 11, 10),   // overlaps the first (IoU 9/11 > 0.7)
        box(5, 0.8, 0, 0, 10, 10),   // same place, other class: kept
        box(1, 0.7, 50, 50, 60, 60), // same class, elsewhere: kept
    };
    const auto kept = ppe::non_max_suppression(c, ppe::DetectParams{0.25, 0.7});
    REQUIRE(kept.size() == 3);
    CHECK(kept[0].score == 0.9);
    CHECK(kept[1].score == 0.8);
    CHECK(kept[2].score == 0.7);
  }

  TEST_CASE("NMS drops boxes at exactly the IoU limit and keeps those below") {
    // IoU of these two is 50 / 150 = 1/3.
    std::vector<ppe::Detection> c{box(0, 0.9, 0, 0, 10, 10), box(0, 0.8, 5, 0, 15, 10)};
    CHECK(ppe::non_max_suppression(c, ppe::DetectParams{0.0, 1.0 / 3.0}).size() == 1);
    CHECK(ppe::non_max_suppression(c, ppe::DetectParams{0.0, 0.34}).size() == 2);
  }

  TEST_CASE("NMS applies the score threshold and keeps tie order") {
    std::vector<ppe::Detection> c{
        box(0, 0.5, 0, 0, 1, 1),
        box(2, 0.5, 10, 10, 11, 11),
        box(3, 0.2, 20, 20, 21, 21),
    };
    const auto kept = ppe::non_max_suppression(c, ppe::DetectParams{0.25, 0.7});
    REQUIRE(kept.size() == 2);
    CHECK(kept[0].class_id == 0);  // stable: first of the tied pair stays first
    CHECK(kept[1].class_id == 2);
    CHECK(ppe::non_max_suppression({}, ppe::DetectParams{}).empty());
  }

  TEST_CASE("postprocess = decode at the threshold, then NMS") {
    const ppe::Letterbox lb = ppe::compute_letterbox(320, 320, 320);
    FakeOutput out(3);
    out.set(0, 50.0F, 50.0F, 20.0F, 20.0F, 1, 0.9F);
    out.set(1, 51.0F, 50.0F, 20.0F, 20.0F, 1, 0.8F);  // suppressed
    out.set(2, 200.0F, 200.0F, 20.0F, 20.0F, 1, 0.2F);  // under 0.25
    const auto kept = ppe::postprocess(out.data.data(), out.count, lb, ppe::DetectParams{});
    REQUIRE(kept.size() == 1);
    CHECK(kept[0].score == doctest::Approx(0.9));
  }
}
