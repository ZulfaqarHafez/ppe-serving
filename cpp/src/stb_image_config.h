// The one place stb_image is configured. Included by stb_image_impl.cpp (with
// STB_IMAGE_IMPLEMENTATION) and by image.cpp, so both see the same settings.
#ifndef PPE_STB_IMAGE_CONFIG_H
#define PPE_STB_IMAGE_CONFIG_H

#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#define STBI_ONLY_BMP
#define STBI_NO_STDIO
#define STBI_NO_LINEAR
#define STBI_NO_HDR
// stb reads this as a macro. NOLINTNEXTLINE(cppcoreguidelines-macro-*,modernize-macro-to-enum)
#define STBI_MAX_DIMENSIONS 16384  // matches ppe::kMaxImageSide

#include "stb_image.h"

#endif  // PPE_STB_IMAGE_CONFIG_H
