#include "ppe/preprocess.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "ppe/error.hpp"
#include "ppe/image.hpp"

namespace ppe {

Letterbox compute_letterbox(int width, int height, int size) {
  if (width <= 0 || height <= 0 || size <= 0) {
    throw Error(ErrorCode::kInvalidArgument, "letterbox needs positive sizes, got " +
                                                 std::to_string(width) + "x" +
                                                 std::to_string(height) + " into " +
                                                 std::to_string(size));
  }
  Letterbox box;
  box.size = size;
  box.ratio = std::min(static_cast<double>(size) / width, static_cast<double>(size) / height);
  // Round half up, as Math.round in the site's ppeDetect.ts. (Python's round()
  // in the script behind samples.json rounds halves to even; none of the five
  // samples hits a half.) Keep at least one pixel so extreme aspect ratios
  // still resize.
  box.width = std::max(1, static_cast<int>(std::floor(width * box.ratio + 0.5)));
  box.height = std::max(1, static_cast<int>(std::floor(height * box.ratio + 0.5)));
  box.pad_x = (size - box.width) / 2;
  box.pad_y = (size - box.height) / 2;
  return box;
}

namespace {

// Pillow's Resample.c, 8 bits per channel: weights are fixed point with 22
// fractional bits (32 - 8 - 2).
constexpr int kPrecisionBits = 32 - 8 - 2;
constexpr std::int64_t kHalf = std::int64_t{1} << (kPrecisionBits - 1);

double bilinear_filter(double x) noexcept {
  x = std::abs(x);
  return x < 1.0 ? 1.0 - x : 0.0;
}

// For each output pixel: the first source index, how many source pixels
// contribute, and their fixed-point weights.
struct Coefficients {
  std::size_t ksize{0};
  std::vector<int> first;
  std::vector<int> count;
  std::vector<std::int32_t> weights;  // ksize per output pixel
};

// precompute_coeffs() and normalize_coeffs_8bpc() in Pillow's Resample.c.
Coefficients precompute(int in_size, int out_size) {
  const double scale = static_cast<double>(in_size) / out_size;
  const double filterscale = std::max(scale, 1.0);
  const double support = 1.0 * filterscale;  // the bilinear filter has support 1
  Coefficients c;
  c.ksize = static_cast<std::size_t>(std::ceil(support)) * 2 + 1;
  const auto out = static_cast<std::size_t>(out_size);
  c.first.assign(out, 0);
  c.count.assign(out, 0);
  c.weights.assign(out * c.ksize, 0);
  std::vector<double> k(c.ksize);
  for (std::size_t xx = 0; xx < out; ++xx) {
    const double center = (static_cast<double>(xx) + 0.5) * scale;
    const double ss = 1.0 / filterscale;
    // Truncation toward zero, as the C cast in Pillow.
    const int xmin = std::max(static_cast<int>(center - support + 0.5), 0);
    const int xmax = std::min(static_cast<int>(center + support + 0.5), in_size) - xmin;
    std::fill(k.begin(), k.end(), 0.0);
    double ww = 0.0;
    for (int x = 0; x < xmax; ++x) {
      const double w = bilinear_filter((x + xmin - center + 0.5) * ss);
      k[static_cast<std::size_t>(x)] = w;
      ww += w;
    }
    if (ww != 0.0) {
      for (int x = 0; x < xmax; ++x) {
        k[static_cast<std::size_t>(x)] /= ww;
      }
    }
    for (std::size_t x = 0; x < c.ksize; ++x) {
      const double v = k[x] * (1 << kPrecisionBits);
      c.weights[xx * c.ksize + x] = static_cast<std::int32_t>(v < 0 ? -0.5 + v : 0.5 + v);
    }
    c.first[xx] = xmin;
    c.count[xx] = xmax;
  }
  return c;
}

std::uint8_t clip8(std::int64_t sum) noexcept {
  return static_cast<std::uint8_t>(std::clamp<std::int64_t>(sum >> kPrecisionBits, 0, 255));
}

}  // namespace

std::vector<std::uint8_t> resize_bilinear_pil(const std::uint8_t* src, int width, int height,
                                              int stride, int channels, int out_width,
                                              int out_height) {
  if (src == nullptr || width <= 0 || height <= 0 || channels <= 0 ||
      stride < width * channels || out_width <= 0 || out_height <= 0) {
    throw Error(ErrorCode::kInvalidArgument, "resize: invalid image or size");
  }
  const auto ch = static_cast<std::size_t>(channels);
  const auto in_h = static_cast<std::size_t>(height);
  const auto out_w = static_cast<std::size_t>(out_width);
  const auto out_h = static_cast<std::size_t>(out_height);
  const auto in_stride = static_cast<std::size_t>(stride);

  // Horizontal pass into a tightly packed out_width x height buffer.
  const Coefficients h = precompute(width, out_width);
  const std::size_t tmp_row = out_w * ch;
  std::vector<std::uint8_t> tmp(tmp_row * in_h);
  for (std::size_t y = 0; y < in_h; ++y) {
    const std::uint8_t* row = src + y * in_stride;
    std::uint8_t* out = tmp.data() + y * tmp_row;
    for (std::size_t xx = 0; xx < out_w; ++xx) {
      const auto xmin = static_cast<std::size_t>(h.first[xx]);
      const auto n = static_cast<std::size_t>(h.count[xx]);
      const std::int32_t* k = &h.weights[xx * h.ksize];
      for (std::size_t c = 0; c < ch; ++c) {
        std::int64_t sum = kHalf;
        for (std::size_t x = 0; x < n; ++x) {
          sum += static_cast<std::int64_t>(row[(x + xmin) * ch + c]) * k[x];
        }
        out[xx * ch + c] = clip8(sum);
      }
    }
  }

  // Vertical pass.
  const Coefficients v = precompute(height, out_height);
  std::vector<std::uint8_t> dst(tmp_row * out_h);
  for (std::size_t yy = 0; yy < out_h; ++yy) {
    const auto ymin = static_cast<std::size_t>(v.first[yy]);
    const auto n = static_cast<std::size_t>(v.count[yy]);
    const std::int32_t* k = &v.weights[yy * v.ksize];
    std::uint8_t* out = dst.data() + yy * tmp_row;
    for (std::size_t i = 0; i < tmp_row; ++i) {
      std::int64_t sum = kHalf;
      for (std::size_t y = 0; y < n; ++y) {
        sum += static_cast<std::int64_t>(tmp[(y + ymin) * tmp_row + i]) * k[y];
      }
      out[i] = clip8(sum);
    }
  }
  return dst;
}

Letterbox preprocess(const ImageView& image, int size, std::vector<float>& tensor) {
  const Letterbox box = compute_letterbox(image.width, image.height, size);
  const std::vector<std::uint8_t> resized = resize_bilinear_pil(
      image.data, image.width, image.height, image.stride, 3, box.width, box.height);
  const auto side = static_cast<std::size_t>(size);
  const std::size_t area = side * side;
  // Same float32 arithmetic as numpy's uint8 -> float32, then / 255.
  constexpr float kScale = 255.0F;
  tensor.assign(3 * area, static_cast<float>(kPadValue) / kScale);
  const auto rw = static_cast<std::size_t>(box.width);
  const auto rh = static_cast<std::size_t>(box.height);
  const auto px = static_cast<std::size_t>(box.pad_x);
  const auto py = static_cast<std::size_t>(box.pad_y);
  float* r = tensor.data();
  float* g = r + area;
  float* b = g + area;
  for (std::size_t y = 0; y < rh; ++y) {
    const std::uint8_t* p = &resized[y * rw * 3];
    const std::size_t base = (y + py) * side + px;
    for (std::size_t x = 0; x < rw; ++x) {
      r[base + x] = static_cast<float>(p[x * 3]) / kScale;
      g[base + x] = static_cast<float>(p[x * 3 + 1]) / kScale;
      b[base + x] = static_cast<float>(p[x * 3 + 2]) / kScale;
    }
  }
  return box;
}

}  // namespace ppe
