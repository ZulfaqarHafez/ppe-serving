// Pre- and post-processing for the PPE detector (YOLOv8s, exported to ONNX).
//
// A C++ port of src/components/demos/ppeDetect.ts on zulfaqarhafez.com and of
// scripts/ppe-samples.py, which produced the reference results in samples.json.
//
// Input `images`: float32 [1, 3, S, S], RGB, letterboxed to a square with grey
// 114 padding, scaled 0 to 1. Output `output0`: float32 [1, 10, N]; column j is
// one candidate: rows 0 to 3 are centre x, centre y, width, height in
// letterboxed pixels, rows 4 to 9 are class scores (already 0 to 1). There is
// no objectness score and no NMS in the graph.

#ifndef PPE_DETECTOR__PPE_CORE_HPP_
#define PPE_DETECTOR__PPE_CORE_HPP_

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace ppe_detector
{

/// Class order of the exported model (ppeDetect.ts PPE_CLASSES).
inline constexpr std::array<const char *, 6> kClassNames = {
  "Gloves", "Helmet", "No-Helmet", "No-gloves", "No-vest", "Vest"};
inline constexpr int kNumClasses = static_cast<int>(kClassNames.size());
inline constexpr uint8_t kPadValue = 114;

/// True for the "No-..." classes, which mean an item is missing.
bool is_missing_item(const std::string & label);

/// Index of a class name, or -1 when unknown.
int class_index(const std::string & label);

/// Where the image goes inside the square model input.
struct Letterbox
{
  int size{0};
  double ratio{1.0};
  int pad_x{0};
  int pad_y{0};
  int width{0};
  int height{0};
};

/// One detection, box corners in original image pixels.
struct Detection
{
  int class_id{0};
  double score{0.0};
  double x1{0.0};
  double y1{0.0};
  double x2{0.0};
  double y2{0.0};
};

/// Same arithmetic as letterbox() in ppeDetect.ts (Math.round, Math.floor).
Letterbox compute_letterbox(int width, int height, int size);

/// Resize an interleaved 8-bit image with the same filter and fixed point
/// arithmetic as Pillow's Image.resize(..., Image.BILINEAR), which made the
/// reference results. Unlike a plain bilinear lookup it averages over the
/// source footprint when shrinking. Returns a tightly packed out_w x out_h image.
std::vector<uint8_t> resize_bilinear_pil(
  const uint8_t * src, int width, int height, int stride, int channels,
  int out_width, int out_height);

/// Letterbox an interleaved RGB8 image (row stride in bytes) into the planar
/// float tensor [3, size, size] the model expects. Returns the letterbox used.
Letterbox preprocess_rgb(
  const uint8_t * rgb, int width, int height, int stride, int size,
  std::vector<float> & tensor);

/// Every candidate whose best class score clears `floor`, mapped back to image
/// pixels (candidates() in ppeDetect.ts). `output` is the [4 + classes, count]
/// block of output0.
std::vector<Detection> decode_candidates(
  const float * output, int count, const Letterbox & box, double floor);

/// Intersection over union of two boxes.
double iou(const Detection & a, const Detection & b);

/// Threshold, then per-class non-maximum suppression, highest score first
/// (selectDetections() in ppeDetect.ts; IoU 0.7 is the Ultralytics default).
std::vector<Detection> select_detections(
  const std::vector<Detection> & all, double threshold, double iou_limit = 0.7);

}  // namespace ppe_detector

#endif  // PPE_DETECTOR__PPE_CORE_HPP_
