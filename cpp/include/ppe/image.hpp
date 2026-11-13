// 8-bit interleaved RGB images: an owning Image and a non-owning ImageView.

#ifndef PPE_IMAGE_HPP
#define PPE_IMAGE_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace ppe {

/// Read-only view of interleaved RGB8 pixels. Does not own the memory; the
/// caller keeps the pixels alive while the view is used.
struct ImageView {
  const std::uint8_t* data{nullptr};
  int width{0};
  int height{0};
  int stride{0};  // bytes from one row to the next, at least 3 * width
};

/// Owning, tightly packed RGB8 image. Movable and copyable like a value.
class Image {
 public:
  Image() = default;
  /// A width x height image filled with `fill`. Throws Error(kInvalidArgument)
  /// for a non-positive or oversized size.
  Image(int width, int height, std::uint8_t fill = 0);

  [[nodiscard]] int width() const noexcept { return width_; }
  [[nodiscard]] int height() const noexcept { return height_; }
  [[nodiscard]] bool empty() const noexcept { return pixels_.empty(); }
  [[nodiscard]] std::uint8_t* data() noexcept { return pixels_.data(); }
  [[nodiscard]] const std::uint8_t* data() const noexcept { return pixels_.data(); }
  [[nodiscard]] std::size_t size_bytes() const noexcept { return pixels_.size(); }
  [[nodiscard]] ImageView view() const noexcept;

 private:
  int width_{0};
  int height_{0};
  std::vector<std::uint8_t> pixels_;
};

/// Largest width or height accepted from an image file.
inline constexpr int kMaxImageSide = 16384;

/// Decode a PNG, JPEG or BMP held in memory to RGB8 (grey is expanded, alpha
/// is dropped). Throws Error(kImageRead) if the bytes are not a decodable image.
Image decode_image(const std::uint8_t* bytes, std::size_t size);

/// Read a whole file into memory. Throws Error(kImageRead) if it cannot be read.
std::vector<std::uint8_t> read_file(const std::string& path);

/// read_file followed by decode_image; the message names the path on failure.
Image load_image(const std::string& path);

}  // namespace ppe

#endif  // PPE_IMAGE_HPP
