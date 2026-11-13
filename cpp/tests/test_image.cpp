#include <doctest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "golden.hpp"
#include "ppe/error.hpp"
#include "ppe/image.hpp"

namespace {

std::string data_dir() { return PPE_TEST_DATA_DIR; }

template <typename Bytes>
ppe::Image decode(const Bytes& bytes) {
  return ppe::decode_image(bytes.data(), bytes.size());
}

template <typename Pixels>
void check_pixels(const ppe::Image& image, const Pixels& expected) {
  REQUIRE(image.size_bytes() == expected.size());
  CHECK(std::equal(expected.begin(), expected.end(), image.data()));
}

ppe::ErrorCode code_of(const std::string& path) {
  try {
    (void)ppe::load_image(path);
  } catch (const ppe::Error& e) {
    return e.code();
  }
  return ppe::ErrorCode::kInvalidArgument;  // not thrown: the test fails on this
}

}  // namespace

TEST_SUITE("image") {
  TEST_CASE("an RGB PNG decodes to its exact pixels") {
    const ppe::Image image = decode(golden::kPngRgb);
    CHECK(image.width() == 3);
    CHECK(image.height() == 2);
    check_pixels(image, golden::kPngRgbPixels);
    const ppe::ImageView v = image.view();
    CHECK(v.stride == 9);
    CHECK(v.data == image.data());
  }

  TEST_CASE("a greyscale PNG is expanded to RGB") {
    const ppe::Image image = decode(golden::kPngGrey);
    std::vector<std::uint8_t> expected(golden::kPngGreyPixels.size() * 3);
    for (std::size_t i = 0; i < expected.size(); ++i) {
      expected[i] = golden::kPngGreyPixels[i / 3];
    }
    check_pixels(image, expected);
  }

  TEST_CASE("alpha is dropped, as Pillow's convert('RGB') does") {
    check_pixels(decode(golden::kPngRgba), golden::kPngRgbaAsRgb);
  }

  TEST_CASE("bytes that are not an image raise kImageRead") {
    const std::vector<std::uint8_t> junk{'n', 'o', 't', ' ', 'a', 'n', ' ', 'i', 'm', 'g'};
    CHECK_THROWS_AS(decode(junk), ppe::Error);
    try {
      (void)decode(junk);
    } catch (const ppe::Error& e) {
      CHECK(e.code() == ppe::ErrorCode::kImageRead);
    }
    CHECK_THROWS_AS(ppe::decode_image(nullptr, 0), ppe::Error);
  }

  TEST_CASE("a truncated PNG raises kImageRead") {
    std::vector<std::uint8_t> cut(golden::kPngRgb.begin(), golden::kPngRgb.end());
    cut.resize(cut.size() / 2);
    CHECK_THROWS_AS(decode(cut), ppe::Error);
  }

  TEST_CASE("missing files, directories and non-images raise kImageRead") {
    CHECK(code_of(data_dir() + "/samples/no-such-file.png") == ppe::ErrorCode::kImageRead);
    CHECK(code_of(data_dir()) == ppe::ErrorCode::kImageRead);
    CHECK(code_of(data_dir() + "/reference/samples.json") == ppe::ErrorCode::kImageRead);
  }

  TEST_CASE("the committed samples decode at their recorded sizes") {
    const ppe::Image image = ppe::load_image(data_dir() + "/samples/site-backs.png");
    CHECK(image.width() == 640);
    CHECK(image.height() == 486);
  }

  TEST_CASE("Image rejects sizes out of range") {
    CHECK_THROWS_AS(ppe::Image(0, 5), ppe::Error);
    CHECK_THROWS_AS(ppe::Image(5, -1), ppe::Error);
    CHECK_THROWS_AS(ppe::Image(ppe::kMaxImageSide + 1, 1), ppe::Error);
    const ppe::Image ok(2, 3, 7);
    CHECK(ok.size_bytes() == 18);
    CHECK(ok.data()[17] == 7);
  }
}
