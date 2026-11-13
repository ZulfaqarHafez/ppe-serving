// Compiles the vendored stb_image (third_party/stb). Built without the
// project's warnings and without clang-tidy, since it is third-party code.
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image_config.h"
