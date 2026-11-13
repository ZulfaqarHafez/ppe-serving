#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "ppe_detector/ppe_core.hpp"

namespace ppe_detector
{

bool is_missing_item(const std::string & label)
{
  return label.rfind("No-", 0) == 0;
}

int class_index(const std::string & label)
{
  for (int c = 0; c < kNumClasses; ++c) {
    if (label == kClassNames[c]) {
      return c;
    }
  }
  return -1;
}

Letterbox compute_letterbox(int width, int height, int size)
{
  Letterbox box;
  box.size = size;
  box.ratio = std::min(
    static_cast<double>(size) / width, static_cast<double>(size) / height);
  // Math.round in JavaScript rounds halves up: floor(x + 0.5).
  box.width = static_cast<int>(std::floor(width * box.ratio + 0.5));
  box.height = static_cast<int>(std::floor(height * box.ratio + 0.5));
  box.pad_x = static_cast<int>(std::floor((size - box.width) / 2.0));
  box.pad_y = static_cast<int>(std::floor((size - box.height) / 2.0));
  return box;
}

namespace
{

// Pillow's Resample.c, 8 bits per channel path.
constexpr int kPrecisionBits = 32 - 8 - 2;

double bilinear_filter(double x)
{
  if (x < 0.0) {
    x = -x;
  }
  return x < 1.0 ? 1.0 - x : 0.0;
}

struct Coeffs
{
  int ksize{0};
  std::vector<int> bounds;   // per output pixel: first source index, count
  std::vector<int> weights;  // fixed point, ksize per output pixel
};

Coeffs precompute_coeffs(int in_size, int out_size)
{
  const double scale = static_cast<double>(in_size) / out_size;
  const double filterscale = std::max(scale, 1.0);
  const double support = 1.0 * filterscale;
  Coeffs c;
  c.ksize = static_cast<int>(std::ceil(support)) * 2 + 1;
  c.bounds.assign(static_cast<size_t>(out_size) * 2, 0);
  c.weights.assign(static_cast<size_t>(out_size) * c.ksize, 0);
  std::vector<double> k(c.ksize);
  for (int xx = 0; xx < out_size; ++xx) {
    const double center = (xx + 0.5) * scale;
    const double ss = 1.0 / filterscale;
    int xmin = static_cast<int>(center - support + 0.5);
    xmin = std::max(xmin, 0);
    int xmax = static_cast<int>(center + support + 0.5);
    xmax = std::min(xmax, in_size) - xmin;
    double ww = 0.0;
    std::fill(k.begin(), k.end(), 0.0);
    for (int x = 0; x < xmax; ++x) {
      const double w = bilinear_filter((x + xmin - center + 0.5) * ss);
      k[x] = w;
      ww += w;
    }
    for (int x = 0; x < xmax; ++x) {
      if (ww != 0.0) {
        k[x] /= ww;
      }
    }
    for (int x = 0; x < c.ksize; ++x) {
      const double v = k[x] * (1 << kPrecisionBits);
      c.weights[static_cast<size_t>(xx) * c.ksize + x] =
        static_cast<int>(v < 0 ? -0.5 + v : 0.5 + v);
    }
    c.bounds[xx * 2] = xmin;
    c.bounds[xx * 2 + 1] = xmax;
  }
  return c;
}

inline uint8_t clip8(int64_t in)
{
  const int64_t v = in >> kPrecisionBits;
  return static_cast<uint8_t>(std::clamp<int64_t>(v, 0, 255));
}

}  // namespace

std::vector<uint8_t> resize_bilinear_pil(
  const uint8_t * src, int width, int height, int stride, int channels,
  int out_width, int out_height)
{
  // Horizontal pass into a tightly packed out_width x height buffer.
  const Coeffs h = precompute_coeffs(width, out_width);
  std::vector<uint8_t> tmp(static_cast<size_t>(out_width) * height * channels);
  for (int y = 0; y < height; ++y) {
    const uint8_t * row = src + static_cast<size_t>(y) * stride;
    uint8_t * out = tmp.data() + static_cast<size_t>(y) * out_width * channels;
    for (int xx = 0; xx < out_width; ++xx) {
      const int xmin = h.bounds[xx * 2];
      const int xmax = h.bounds[xx * 2 + 1];
      const int * k = &h.weights[static_cast<size_t>(xx) * h.ksize];
      for (int ch = 0; ch < channels; ++ch) {
        int64_t ss = 1 << (kPrecisionBits - 1);
        for (int x = 0; x < xmax; ++x) {
          ss += static_cast<int64_t>(row[(x + xmin) * channels + ch]) * k[x];
        }
        out[xx * channels + ch] = clip8(ss);
      }
    }
  }
  // Vertical pass.
  const Coeffs v = precompute_coeffs(height, out_height);
  const size_t row_bytes = static_cast<size_t>(out_width) * channels;
  std::vector<uint8_t> dst(row_bytes * out_height);
  for (int yy = 0; yy < out_height; ++yy) {
    const int ymin = v.bounds[yy * 2];
    const int ymax = v.bounds[yy * 2 + 1];
    const int * k = &v.weights[static_cast<size_t>(yy) * v.ksize];
    uint8_t * out = dst.data() + static_cast<size_t>(yy) * row_bytes;
    for (size_t i = 0; i < row_bytes; ++i) {
      int64_t ss = 1 << (kPrecisionBits - 1);
      for (int y = 0; y < ymax; ++y) {
        ss += static_cast<int64_t>(tmp[static_cast<size_t>(y + ymin) * row_bytes + i]) * k[y];
      }
      out[i] = clip8(ss);
    }
  }
  return dst;
}

Letterbox preprocess_rgb(
  const uint8_t * rgb, int width, int height, int stride, int size,
  std::vector<float> & tensor)
{
  const Letterbox box = compute_letterbox(width, height, size);
  const std::vector<uint8_t> resized =
    resize_bilinear_pil(rgb, width, height, stride, 3, box.width, box.height);
  const size_t area = static_cast<size_t>(size) * size;
  tensor.assign(3 * area, kPadValue / 255.0f);
  for (int y = 0; y < box.height; ++y) {
    for (int x = 0; x < box.width; ++x) {
      const uint8_t * p = &resized[(static_cast<size_t>(y) * box.width + x) * 3];
      const size_t i = static_cast<size_t>(y + box.pad_y) * size + (x + box.pad_x);
      tensor[i] = p[0] / 255.0f;
      tensor[area + i] = p[1] / 255.0f;
      tensor[2 * area + i] = p[2] / 255.0f;
    }
  }
  return box;
}

std::vector<Detection> decode_candidates(
  const float * output, int count, const Letterbox & box, double floor)
{
  std::vector<Detection> found;
  const double max_x = box.width / box.ratio;
  const double max_y = box.height / box.ratio;
  auto clamp_x = [max_x](double v) {return std::min(std::max(v, 0.0), max_x);};
  auto clamp_y = [max_y](double v) {return std::min(std::max(v, 0.0), max_y);};
  for (int j = 0; j < count; ++j) {
    double best = 0.0;
    int cls = 0;
    for (int c = 0; c < kNumClasses; ++c) {
      const double s = output[static_cast<size_t>(4 + c) * count + j];
      if (s > best) {
        best = s;
        cls = c;
      }
    }
    if (best < floor) {
      continue;
    }
    const double cx = output[j];
    const double cy = output[static_cast<size_t>(count) + j];
    const double w = output[static_cast<size_t>(2) * count + j];
    const double h = output[static_cast<size_t>(3) * count + j];
    Detection d;
    d.class_id = cls;
    d.score = best;
    d.x1 = clamp_x((cx - w / 2 - box.pad_x) / box.ratio);
    d.y1 = clamp_y((cy - h / 2 - box.pad_y) / box.ratio);
    d.x2 = clamp_x((cx + w / 2 - box.pad_x) / box.ratio);
    d.y2 = clamp_y((cy + h / 2 - box.pad_y) / box.ratio);
    found.push_back(d);
  }
  return found;
}

double iou(const Detection & a, const Detection & b)
{
  const double w = std::max(0.0, std::min(a.x2, b.x2) - std::max(a.x1, b.x1));
  const double h = std::max(0.0, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
  const double inter = w * h;
  const double uni = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return uni > 0 ? inter / uni : 0.0;
}

std::vector<Detection> select_detections(
  const std::vector<Detection> & all, double threshold, double iou_limit)
{
  std::vector<Detection> sorted;
  for (const auto & d : all) {
    if (d.score >= threshold) {
      sorted.push_back(d);
    }
  }
  // Array.prototype.sort is stable, so ties keep candidate order.
  std::stable_sort(
    sorted.begin(), sorted.end(),
    [](const Detection & a, const Detection & b) {return a.score > b.score;});
  std::vector<Detection> kept;
  for (const auto & d : sorted) {
    bool keep = true;
    for (const auto & k : kept) {
      if (k.class_id == d.class_id && iou(k, d) >= iou_limit) {
        keep = false;
        break;
      }
    }
    if (keep) {
      kept.push_back(d);
    }
  }
  return kept;
}

}  // namespace ppe_detector
