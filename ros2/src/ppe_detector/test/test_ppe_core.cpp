// Unit tests for letterbox, resize, tensor layout, decode and NMS.

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "ppe_detector/ppe_core.hpp"

using ppe_detector::Detection;
using ppe_detector::Letterbox;

TEST(Letterbox, LandscapeImageIsCentredVertically)
{
  // 640 x 486 is the "site-backs" sample: ratio 0.5, 320 x 243, 38 px above.
  const Letterbox b = ppe_detector::compute_letterbox(640, 486, 320);
  EXPECT_DOUBLE_EQ(b.ratio, 0.5);
  EXPECT_EQ(b.width, 320);
  EXPECT_EQ(b.height, 243);
  EXPECT_EQ(b.pad_x, 0);
  EXPECT_EQ(b.pad_y, 38);
}

TEST(Letterbox, PortraitAndRoundingMatchJavaScript)
{
  // 300 x 401: ratio 320 / 401, width 239.40 rounds to 239, pad floor(81 / 2).
  const Letterbox b = ppe_detector::compute_letterbox(300, 401, 320);
  EXPECT_EQ(b.height, 320);
  EXPECT_EQ(b.width, 239);
  EXPECT_EQ(b.pad_x, 40);
  EXPECT_EQ(b.pad_y, 0);
  // Exact halves round up as Math.round does (5 * 0.5 = 2.5 -> 3).
  const Letterbox c = ppe_detector::compute_letterbox(10, 5, 5);
  EXPECT_EQ(c.height, 3);
}

TEST(Resize, ConstantImageStaysConstant)
{
  std::vector<uint8_t> img(37 * 23 * 3, 200);
  const auto out = ppe_detector::resize_bilinear_pil(img.data(), 37, 23, 37 * 3, 3, 16, 10);
  ASSERT_EQ(out.size(), 16u * 10u * 3u);
  for (auto v : out) {
    EXPECT_EQ(v, 200);
  }
}

TEST(Resize, HalvingAveragesPairs)
{
  // Pillow's bilinear filter widens with the scale: halving 0, 100, 200, 250
  // weighs each output over a 4-pixel footprint (weights 1/8, 3/8, 3/8, 1/8,
  // clipped at the border). Expected values computed by hand from Resample.c.
  const std::vector<uint8_t> row = {0, 100, 200, 250};
  const auto out = ppe_detector::resize_bilinear_pil(row.data(), 4, 1, 4, 1, 2, 1);
  ASSERT_EQ(out.size(), 2u);
  // Output 0: centre 1.0, taps x=0..2 with weights 3/7, 3/7, 1/7 -> 71.43.
  EXPECT_EQ(out[0], 71);
  // Output 1: centre 3.0, taps x=1..3 with weights 1/7, 3/7, 3/7 -> 207.14.
  EXPECT_EQ(out[1], 207);
}

TEST(Preprocess, PlanarRgbWithGreyPadding)
{
  // 4 x 2 image, all pixels (255, 0, 51), into an 8 x 8 square.
  std::vector<uint8_t> img(4 * 2 * 3);
  for (size_t i = 0; i < img.size(); i += 3) {
    img[i] = 255;
    img[i + 1] = 0;
    img[i + 2] = 51;
  }
  std::vector<float> t;
  const Letterbox b = ppe_detector::preprocess_rgb(img.data(), 4, 2, 12, 8, t);
  ASSERT_EQ(t.size(), 3u * 64u);
  EXPECT_EQ(b.width, 8);
  EXPECT_EQ(b.height, 4);
  EXPECT_EQ(b.pad_y, 2);
  const float grey = 114.0f / 255.0f;
  EXPECT_FLOAT_EQ(t[0], grey);          // R, row 0 is padding
  EXPECT_FLOAT_EQ(t[2 * 8 + 3], 1.0f);  // R, row 2 is image
  EXPECT_FLOAT_EQ(t[64 + 2 * 8 + 3], 0.0f);         // G plane
  EXPECT_FLOAT_EQ(t[128 + 2 * 8 + 3], 51.0f / 255.0f);  // B plane
  EXPECT_FLOAT_EQ(t[128 + 7 * 8], grey);  // B, last row is padding
}

namespace
{
// Build an output0 block [10, count] with the given candidates.
struct Cand
{
  float cx, cy, w, h;
  int cls;
  float score;
};
std::vector<float> make_output(const std::vector<Cand> & cands)
{
  const int n = static_cast<int>(cands.size());
  std::vector<float> o(static_cast<size_t>(10) * n, 0.0f);
  for (int j = 0; j < n; ++j) {
    o[j] = cands[j].cx;
    o[n + j] = cands[j].cy;
    o[2 * n + j] = cands[j].w;
    o[3 * n + j] = cands[j].h;
    o[(4 + cands[j].cls) * n + j] = cands[j].score;
    // A weaker second class score that must not win.
    o[(4 + (cands[j].cls + 1) % 6) * n + j] = cands[j].score / 2;
  }
  return o;
}
}  // namespace

TEST(Decode, MapsBackToImagePixelsAndAppliesFloor)
{
  const Letterbox b = ppe_detector::compute_letterbox(640, 486, 320);  // pad_y 38, ratio 0.5
  const auto o = make_output({{100, 138, 20, 40, 2, 0.6f}, {50, 50, 10, 10, 1, 0.04f}});
  const auto d = ppe_detector::decode_candidates(o.data(), 2, b, 0.05);
  ASSERT_EQ(d.size(), 1u);
  EXPECT_EQ(d[0].class_id, 2);
  EXPECT_NEAR(d[0].score, 0.6, 1e-6);
  EXPECT_DOUBLE_EQ(d[0].x1, 180.0);
  EXPECT_DOUBLE_EQ(d[0].x2, 220.0);
  EXPECT_DOUBLE_EQ(d[0].y1, 160.0);  // (138 - 20 - 38) / 0.5
  EXPECT_DOUBLE_EQ(d[0].y2, 240.0);
}

TEST(Decode, ClampsToImage)
{
  const Letterbox b = ppe_detector::compute_letterbox(640, 486, 320);
  const auto o = make_output({{5, 40, 20, 10, 0, 0.9f}});
  const auto d = ppe_detector::decode_candidates(o.data(), 1, b, 0.05);
  ASSERT_EQ(d.size(), 1u);
  EXPECT_DOUBLE_EQ(d[0].x1, 0.0);
  EXPECT_DOUBLE_EQ(d[0].y1, 0.0);  // (40 - 5 - 38) / 0.5 < 0
}

TEST(Nms, SuppressesSameClassOverlapOnly)
{
  std::vector<Detection> all = {
    {1, 0.50, 0, 0, 100, 100},
    {1, 0.90, 5, 5, 105, 105},     // overlaps the first, IoU ~0.82
    {2, 0.70, 5, 5, 105, 105},     // other class: kept
    {1, 0.60, 300, 300, 400, 400},  // same class, far away: kept
    {4, 0.20, 0, 0, 10, 10},       // below threshold
  };
  const auto kept = ppe_detector::select_detections(all, 0.25, 0.7);
  ASSERT_EQ(kept.size(), 3u);
  EXPECT_NEAR(kept[0].score, 0.90, 1e-9);
  EXPECT_EQ(kept[1].class_id, 2);
  EXPECT_NEAR(kept[2].score, 0.60, 1e-9);
}

TEST(Nms, KeepsOverlapBelowLimit)
{
  // IoU of these two is 0.5 / 1.5 = 0.333 < 0.7, so both stay.
  std::vector<Detection> all = {{0, 0.8, 0, 0, 10, 10}, {0, 0.7, 0, 5, 10, 15}};
  EXPECT_NEAR(ppe_detector::iou(all[0], all[1]), 1.0 / 3.0, 1e-9);
  EXPECT_EQ(ppe_detector::select_detections(all, 0.25).size(), 2u);
}

TEST(Classes, MissingItemAndIndex)
{
  EXPECT_TRUE(ppe_detector::is_missing_item("No-Helmet"));
  EXPECT_FALSE(ppe_detector::is_missing_item("Helmet"));
  EXPECT_EQ(ppe_detector::class_index("No-Helmet"), 2);
  EXPECT_EQ(ppe_detector::class_index("Vest"), 5);
  EXPECT_EQ(ppe_detector::class_index("hat"), -1);
}
