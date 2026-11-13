#include "ppe/postprocess.hpp"

#include <algorithm>
#include <cstddef>
#include <utility>
#include <vector>

#include "ppe/error.hpp"
#include "ppe/preprocess.hpp"

namespace ppe {

std::vector<Detection> decode_candidates(const float* output, std::size_t count,
                                         const Letterbox& box, double floor) {
  if (output == nullptr && count > 0) {
    throw Error(ErrorCode::kInvalidArgument, "decode: no output data");
  }
  if (box.ratio <= 0.0) {
    throw Error(ErrorCode::kInvalidArgument, "decode: letterbox ratio must be positive");
  }
  std::vector<Detection> found;
  const double max_x = box.width / box.ratio;
  const double max_y = box.height / box.ratio;
  const auto clamp_x = [max_x](double v) { return std::clamp(v, 0.0, max_x); };
  const auto clamp_y = [max_y](double v) { return std::clamp(v, 0.0, max_y); };
  const auto at = [output, count](std::size_t row, std::size_t col) {
    return static_cast<double>(output[row * count + col]);
  };
  for (std::size_t j = 0; j < count; ++j) {
    double best = 0.0;
    int cls = 0;
    for (int c = 0; c < kNumClasses; ++c) {
      const double s = at(4 + static_cast<std::size_t>(c), j);
      if (s > best) {
        best = s;
        cls = c;
      }
    }
    if (best < floor) {
      continue;
    }
    const double cx = at(0, j);
    const double cy = at(1, j);
    const double w = at(2, j);
    const double h = at(3, j);
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

double iou(const Detection& a, const Detection& b) noexcept {
  const double w = std::max(0.0, std::min(a.x2, b.x2) - std::max(a.x1, b.x1));
  const double h = std::max(0.0, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
  const double inter = w * h;
  const double uni = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return uni > 0.0 ? inter / uni : 0.0;
}

std::vector<Detection> non_max_suppression(std::vector<Detection> candidates,
                                           const DetectParams& params) {
  candidates.erase(std::remove_if(candidates.begin(), candidates.end(),
                                  [&params](const Detection& d) {
                                    return !(d.score >= params.score_threshold);
                                  }),
                   candidates.end());
  std::stable_sort(candidates.begin(), candidates.end(),
                   [](const Detection& a, const Detection& b) { return a.score > b.score; });
  std::vector<Detection> kept;
  for (const Detection& d : candidates) {
    const bool overlaps = std::any_of(kept.begin(), kept.end(), [&](const Detection& k) {
      return k.class_id == d.class_id && iou(k, d) >= params.iou_threshold;
    });
    if (!overlaps) {
      kept.push_back(d);
    }
  }
  return kept;
}

std::vector<Detection> postprocess(const float* output, std::size_t count, const Letterbox& box,
                                   const DetectParams& params) {
  return non_max_suppression(decode_candidates(output, count, box, params.score_threshold),
                             params);
}

}  // namespace ppe
