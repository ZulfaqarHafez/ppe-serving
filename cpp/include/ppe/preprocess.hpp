// Letterbox and resize: the model input is the image scaled to fit a square,
// centred on grey 114, as planar float RGB in 0..1.
//
// Adapted from ros2/src/ppe_detector (ppe_core) in this repository, which
// ports letterbox() in the site's ppeDetect.ts and Pillow's bilinear resize.

#ifndef PPE_PREPROCESS_HPP
#define PPE_PREPROCESS_HPP

#include <cstdint>
#include <vector>

#include "ppe/image.hpp"

namespace ppe {

inline constexpr std::uint8_t kPadValue = 114;

/// Where the resized image sits inside the square model input.
struct Letterbox {
  int size{0};        // side of the square input
  double ratio{1.0};  // resized / original
  int pad_x{0};
  int pad_y{0};
  int width{0};  // resized width
  int height{0};
};

/// Same arithmetic as the reference: ratio = min(S/W, S/H), resized side =
/// round half up, padding = floor((S - side) / 2). Throws
/// Error(kInvalidArgument) for non-positive sizes.
Letterbox compute_letterbox(int width, int height, int size);

/// Resize interleaved 8-bit pixels with the filter and fixed-point arithmetic
/// of Pillow's Image.resize(..., Image.BILINEAR) (Resample.c), which produced
/// the reference results. When shrinking it averages over the source
/// footprint, unlike a plain 2x2 bilinear lookup. Returns a tightly packed
/// out_width x out_height x channels buffer.
std::vector<std::uint8_t> resize_bilinear_pil(const std::uint8_t* src, int width, int height,
                                              int stride, int channels, int out_width,
                                              int out_height);

/// Letterbox an RGB image into `tensor` ([3, size, size], planar, value / 255).
/// The vector is resized as needed so a caller can reuse its allocation.
Letterbox preprocess(const ImageView& image, int size, std::vector<float>& tensor);

}  // namespace ppe

#endif  // PPE_PREPROCESS_HPP
