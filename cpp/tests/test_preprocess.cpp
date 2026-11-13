#include <doctest.h>

#include <cstddef>
#include <cstdint>
#include <vector>

#include "golden.hpp"
#include "ppe/error.hpp"
#include "ppe/image.hpp"
#include "ppe/preprocess.hpp"

namespace {

std::vector<std::uint8_t> source() {
  std::vector<std::uint8_t> s;
  for (int y = 0; y < golden::kSrcHeight; ++y) {
    for (int x = 0; x < golden::kSrcWidth; ++x) {
      for (int c = 0; c < 3; ++c) {
        s.push_back(static_cast<std::uint8_t>((x * 37 + y * 91 + c * 53) % 256));
      }
    }
  }
  return s;
}

template <typename Expected>
void check_resize(int w, int h, const Expected& expected) {
  const std::vector<std::uint8_t> src = source();
  const auto out = ppe::resize_bilinear_pil(src.data(), golden::kSrcWidth, golden::kSrcHeight,
                                            golden::kSrcWidth * 3, 3, w, h);
  REQUIRE(out.size() == expected.size());
  std::size_t diffs = 0;
  for (std::size_t i = 0; i < out.size(); ++i) {
    diffs += out[i] != expected[i] ? 1U : 0U;
  }
  CHECK(diffs == 0);
}

}  // namespace

TEST_SUITE("preprocess") {
  TEST_CASE("letterbox of the sample sizes") {
    const ppe::Letterbox a = ppe::compute_letterbox(640, 486, 320);
    CHECK(a.ratio == doctest::Approx(0.5));
    CHECK(a.width == 320);
    CHECK(a.height == 243);
    CHECK(a.pad_x == 0);
    CHECK(a.pad_y == 38);
    const ppe::Letterbox b = ppe::compute_letterbox(640, 360, 320);
    CHECK(b.height == 180);
    CHECK(b.pad_y == 70);
    const ppe::Letterbox c = ppe::compute_letterbox(360, 640, 320);
    CHECK(c.width == 180);
    CHECK(c.pad_x == 70);
    CHECK(c.pad_y == 0);
  }

  TEST_CASE("letterbox rounds halves up, like Math.round") {
    // 485 * 0.5 = 242.5 -> 243; padding floor((320 - 243) / 2) = 38.
    const ppe::Letterbox box = ppe::compute_letterbox(640, 485, 320);
    CHECK(box.height == 243);
    CHECK(box.pad_y == 38);
  }

  TEST_CASE("letterbox keeps at least one pixel and rejects bad sizes") {
    const ppe::Letterbox thin = ppe::compute_letterbox(10000, 1, 320);
    CHECK(thin.width == 320);
    CHECK(thin.height == 1);
    CHECK_THROWS_AS(ppe::compute_letterbox(0, 10, 320), ppe::Error);
    CHECK_THROWS_AS(ppe::compute_letterbox(10, 10, 0), ppe::Error);
  }

  TEST_CASE("resize matches Pillow's bilinear exactly") {
    check_resize(5, 3, golden::kResize5x3);       // shrink both ways
    check_resize(20, 11, golden::kResize20x11);   // enlarge both ways
    check_resize(13, 4, golden::kResize13x4);     // one axis unchanged
  }

  TEST_CASE("resize to the same size is the identity") {
    const std::vector<std::uint8_t> src = source();
    const auto out = ppe::resize_bilinear_pil(src.data(), golden::kSrcWidth, golden::kSrcHeight,
                                              golden::kSrcWidth * 3, 3, golden::kSrcWidth,
                                              golden::kSrcHeight);
    CHECK(out == src);
  }

  TEST_CASE("resize honours the row stride") {
    // Two RGB pixels per row plus 2 bytes of padding that must be ignored.
    const std::vector<std::uint8_t> padded{10, 20, 30, 40, 50, 60, 255, 255,
                                           70, 80, 90, 100, 110, 120, 255, 255};
    const auto out = ppe::resize_bilinear_pil(padded.data(), 2, 2, 8, 3, 2, 2);
    const std::vector<std::uint8_t> expected{10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120};
    CHECK(out == expected);
  }

  TEST_CASE("resize of a constant image stays constant") {
    const std::vector<std::uint8_t> flat(17 * 9 * 3, 200);
    const auto out = ppe::resize_bilinear_pil(flat.data(), 17, 9, 17 * 3, 3, 6, 4);
    for (const std::uint8_t v : out) {
      CHECK(v == 200);
    }
  }

  TEST_CASE("resize rejects invalid arguments") {
    const std::vector<std::uint8_t> src(12, 0);
    CHECK_THROWS_AS(ppe::resize_bilinear_pil(nullptr, 2, 2, 6, 3, 1, 1), ppe::Error);
    CHECK_THROWS_AS(ppe::resize_bilinear_pil(src.data(), 2, 2, 5, 3, 1, 1), ppe::Error);
    CHECK_THROWS_AS(ppe::resize_bilinear_pil(src.data(), 2, 2, 6, 3, 0, 1), ppe::Error);
  }

  TEST_CASE("preprocess pads with grey 114 and writes planar RGB / 255") {
    ppe::Image image(4, 2);
    for (int x = 0; x < 4; ++x) {
      for (int y = 0; y < 2; ++y) {
        std::uint8_t* p = image.data() + (y * 4 + x) * 3;
        p[0] = 255;
        p[1] = 0;
        p[2] = 51;
      }
    }
    std::vector<float> tensor;
    const ppe::Letterbox box = ppe::preprocess(image.view(), 8, tensor);
    REQUIRE(tensor.size() == 3U * 64U);
    CHECK(box.width == 8);
    CHECK(box.height == 4);
    CHECK(box.pad_y == 2);
    const float pad = 114.0F / 255.0F;
    // Row 0 is padding, row 2 is image.
    CHECK(tensor[0] == pad);
    CHECK(tensor[64] == pad);
    CHECK(tensor[128] == pad);
    CHECK(tensor[2 * 8 + 3] == 1.0F);
    CHECK(tensor[64 + 2 * 8 + 3] == 0.0F);
    CHECK(tensor[128 + 2 * 8 + 3] == 51.0F / 255.0F);
    CHECK(tensor[7 * 8] == pad);
  }

  TEST_CASE("preprocess reuses the caller's buffer") {
    const ppe::Image image(10, 10, 9);
    std::vector<float> tensor;
    (void)ppe::preprocess(image.view(), 16, tensor);
    const float* before = tensor.data();
    (void)ppe::preprocess(image.view(), 16, tensor);
    CHECK(tensor.data() == before);
  }
}
