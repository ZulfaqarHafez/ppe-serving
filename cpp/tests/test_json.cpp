#include <doctest.h>

#include <cmath>
#include <limits>
#include <string>

#include "ppe/json.hpp"
#include "ppe/postprocess.hpp"

TEST_SUITE("json") {
  TEST_CASE("strings are quoted and escaped") {
    CHECK(ppe::json_string("plain") == "\"plain\"");
    CHECK(ppe::json_string("a\"b\\c") == "\"a\\\"b\\\\c\"");
    CHECK(ppe::json_string("x\ny\tz\r") == "\"x\\ny\\tz\\r\"");
    CHECK(ppe::json_string(std::string("\x01\x1f", 2)) == "\"\\u0001\\u001f\"");
    CHECK(ppe::json_string("caf\xc3\xa9") == "\"caf\xc3\xa9\"");  // UTF-8 unchanged
  }

  TEST_CASE("numbers use the shortest round-trip form") {
    CHECK(ppe::json_number(0.25) == "0.25");
    CHECK(ppe::json_number(0.7) == "0.7");
    CHECK(ppe::json_number(320.0) == "320");
    CHECK(ppe::json_number(-1.5) == "-1.5");
    const double third = 1.0 / 3.0;
    CHECK(std::stod(ppe::json_number(third)) == third);
    const auto f = static_cast<double>(0.55322265625F);
    CHECK(std::stod(ppe::json_number(f)) == f);
  }

  TEST_CASE("NaN and infinity become null") {
    CHECK(ppe::json_number(std::nan("")) == "null");
    CHECK(ppe::json_number(std::numeric_limits<double>::infinity()) == "null");
  }

  TEST_CASE("a detection and an image result") {
    const ppe::Detection d{5, 0.5, 1.0, 2.5, 3.0, 4.0};
    CHECK(ppe::detection_to_json(d) ==
          R"({"label":"Vest","class_id":5,"score":0.5,"box":[1,2.5,3,4]})");
    const ppe::Detection bad{42, 0.5, 0, 0, 0, 0};
    CHECK(ppe::detection_to_json(bad).find("\"unknown\"") != std::string::npos);

    ppe::ImageResult r{"dir/a \"b\".png", 640, 360, {d, d}};
    CHECK(ppe::image_result_to_json(r) ==
          R"({"file":"dir/a \"b\".png","width":640,"height":360,"detections":[)"
          R"({"label":"Vest","class_id":5,"score":0.5,"box":[1,2.5,3,4]},)"
          R"({"label":"Vest","class_id":5,"score":0.5,"box":[1,2.5,3,4]}]})");
    r.detections.clear();
    CHECK(ppe::image_result_to_json(r).find("\"detections\":[]}") != std::string::npos);
  }
}
