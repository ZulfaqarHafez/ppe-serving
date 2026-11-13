// Decode the raw YOLOv8 output and apply per-class non-maximum suppression.
//
// output0 is float32 [1, 4 + classes, N]; column j is one candidate: rows 0
// to 3 are centre x, centre y, width, height in letterboxed pixels, the other
// rows are class scores already in 0..1. There is no objectness score and no
// NMS in the graph. Adapted from ros2/src/ppe_detector in this repository.

#ifndef PPE_POSTPROCESS_HPP
#define PPE_POSTPROCESS_HPP

#include <array>
#include <cstddef>
#include <string_view>
#include <vector>

#include "ppe/preprocess.hpp"

namespace ppe {

/// Class order of the exported model.
inline constexpr std::array<std::string_view, 6> kClassNames = {"Gloves",    "Helmet",  "No-Helmet",
                                                                "No-gloves", "No-vest", "Vest"};
inline constexpr int kNumClasses = static_cast<int>(kClassNames.size());
inline constexpr int kOutputRows = 4 + kNumClasses;

/// One detection; box corners in original image pixels.
struct Detection {
  int class_id{0};
  double score{0.0};
  double x1{0.0};
  double y1{0.0};
  double x2{0.0};
  double y2{0.0};
};

/// Thresholds for one call.
struct DetectParams {
  double score_threshold{0.25};
  double iou_threshold{0.7};  // the Ultralytics default
};

/// Every candidate whose best class score is at least `floor`, mapped back to
/// image pixels and clamped to the image. `output` holds kOutputRows * count
/// floats, row-major. Ties between classes go to the lower class index.
std::vector<Detection> decode_candidates(const float* output, std::size_t count,
                                         const Letterbox& box, double floor);

/// Intersection over union; 0 when the union is empty.
double iou(const Detection& a, const Detection& b) noexcept;

/// Keep detections scoring at least `params.score_threshold`, sorted by score
/// (stable, so ties keep candidate order), then drop any box whose IoU with a
/// kept box of the same class is at least `params.iou_threshold`.
std::vector<Detection> non_max_suppression(std::vector<Detection> candidates,
                                           const DetectParams& params);

/// decode_candidates at the score threshold, then non_max_suppression.
std::vector<Detection> postprocess(const float* output, std::size_t count, const Letterbox& box,
                                   const DetectParams& params);

}  // namespace ppe

#endif  // PPE_POSTPROCESS_HPP
