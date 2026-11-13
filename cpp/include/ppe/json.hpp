// Minimal JSON writing for the CLI's output: strings are escaped, numbers are
// written in the shortest form that reads back to the same double.

#ifndef PPE_JSON_HPP
#define PPE_JSON_HPP

#include <string>
#include <string_view>
#include <vector>

#include "ppe/postprocess.hpp"

namespace ppe {

/// `text` as a quoted JSON string with ", \ and control characters escaped.
std::string json_string(std::string_view text);

/// `value` as a JSON number, shortest round-trip form; NaN and infinities
/// (which JSON cannot hold) become null.
std::string json_number(double value);

/// One image's result for the CLI output.
struct ImageResult {
  std::string file;
  int width{0};
  int height{0};
  std::vector<Detection> detections;
};

/// {"label":"Vest","class_id":5,"score":0.55,"box":[x1,y1,x2,y2]}
std::string detection_to_json(const Detection& detection);

/// {"file":...,"width":...,"height":...,"detections":[...]}
std::string image_result_to_json(const ImageResult& result);

}  // namespace ppe

#endif  // PPE_JSON_HPP
