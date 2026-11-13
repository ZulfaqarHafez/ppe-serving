#include "ppe/image.hpp"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <system_error>
#include <vector>

#include "ppe/error.hpp"
#include "stb_image_config.h"

namespace ppe {

namespace {

constexpr int kChannels = 3;

struct StbiFree {
  void operator()(stbi_uc* pixels) const noexcept { stbi_image_free(pixels); }
};
using StbiPixels = std::unique_ptr<stbi_uc, StbiFree>;

}  // namespace

Image::Image(int width, int height, std::uint8_t fill) : width_(width), height_(height) {
  if (width <= 0 || height <= 0 || width > kMaxImageSide || height > kMaxImageSide) {
    throw Error(ErrorCode::kInvalidArgument, "image size " + std::to_string(width) + "x" +
                                                 std::to_string(height) + " is out of range");
  }
  pixels_.assign(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * kChannels,
                 fill);
}

ImageView Image::view() const noexcept {
  return ImageView{pixels_.data(), width_, height_, width_ * kChannels};
}

Image decode_image(const std::uint8_t* bytes, std::size_t size) {
  if (bytes == nullptr || size == 0) {
    throw Error(ErrorCode::kImageRead, "no image data");
  }
  if (size > static_cast<std::size_t>(INT_MAX)) {
    throw Error(ErrorCode::kImageRead, "image data is too large");
  }
  int width = 0;
  int height = 0;
  int channels_in_file = 0;
  const StbiPixels pixels(stbi_load_from_memory(bytes, static_cast<int>(size), &width, &height,
                                                &channels_in_file, kChannels));
  if (!pixels) {
    const char* reason = stbi_failure_reason();
    throw Error(ErrorCode::kImageRead,
                std::string("cannot decode image: ") + (reason != nullptr ? reason : "unknown"));
  }
  Image image(width, height);
  std::memcpy(image.data(), pixels.get(), image.size_bytes());
  return image;
}

std::vector<std::uint8_t> read_file(const std::string& path) {
  std::error_code ec;
  if (!std::filesystem::is_regular_file(path, ec)) {
    throw Error(ErrorCode::kImageRead, "no such file: " + path);
  }
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  if (!file) {
    throw Error(ErrorCode::kImageRead, "cannot open " + path);
  }
  const std::streamoff end = file.tellg();
  if (end < 0) {
    throw Error(ErrorCode::kImageRead, "cannot read " + path);
  }
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
  file.seekg(0);
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): istream reads char
  if (!file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(end))) {
    throw Error(ErrorCode::kImageRead, "cannot read " + path);
  }
  return bytes;
}

Image load_image(const std::string& path) {
  const std::vector<std::uint8_t> bytes = read_file(path);
  try {
    return decode_image(bytes.data(), bytes.size());
  } catch (const Error& e) {
    throw Error(e.code(), path + ": " + e.what());
  }
}

}  // namespace ppe
