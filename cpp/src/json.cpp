#include "ppe/json.hpp"

#include <array>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <string>
#include <string_view>
#include <system_error>

#include "ppe/postprocess.hpp"

namespace ppe {

std::string json_string(std::string_view text) {
  static constexpr std::string_view kHex = "0123456789abcdef";
  std::string out;
  out.reserve(text.size() + 2);
  out.push_back('"');
  for (const char ch : text) {
    switch (ch) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default: {
        const auto byte = static_cast<unsigned char>(ch);
        if (byte < 0x20) {
          out += "\\u00";
          out.push_back(kHex[byte >> 4U]);
          out.push_back(kHex[byte & 0x0FU]);
        } else {
          out.push_back(ch);  // UTF-8 bytes pass through unchanged
        }
      }
    }
  }
  out.push_back('"');
  return out;
}

std::string json_number(double value) {
  if (!std::isfinite(value)) {
    return "null";
  }
  std::array<char, 32> buf{};
  const auto [end, ec] = std::to_chars(buf.data(), buf.data() + buf.size(), value);
  if (ec != std::errc{}) {
    return "null";  // cannot happen with 32 bytes, but never write garbage
  }
  return {buf.data(), static_cast<std::size_t>(end - buf.data())};
}

std::string detection_to_json(const Detection& detection) {
  const bool known = detection.class_id >= 0 && detection.class_id < kNumClasses;
  const std::string_view label =
      known ? kClassNames.at(static_cast<std::size_t>(detection.class_id)) : "unknown";
  std::string out = "{\"label\":" + json_string(label);
  out += ",\"class_id\":" + std::to_string(detection.class_id);
  out += ",\"score\":" + json_number(detection.score);
  out += ",\"box\":[" + json_number(detection.x1) + "," + json_number(detection.y1) + "," +
         json_number(detection.x2) + "," + json_number(detection.y2) + "]}";
  return out;
}

std::string image_result_to_json(const ImageResult& result) {
  std::string out = "{\"file\":" + json_string(result.file);
  out += ",\"width\":" + std::to_string(result.width);
  out += ",\"height\":" + std::to_string(result.height);
  out += ",\"detections\":[";
  for (std::size_t i = 0; i < result.detections.size(); ++i) {
    if (i > 0) {
      out += ",";
    }
    out += detection_to_json(result.detections[i]);
  }
  out += "]}";
  return out;
}

}  // namespace ppe
