# Vendored third-party code

| Library | File | Version | Source (pinned commit) | SHA-256 of the file | Licence |
|---|---|---|---|---|---|
| stb_image | `stb/stb_image.h` | v2.32 | github.com/nothings/stb at `9600522de53973336fa033a289858a4354cbb04c` | `deb4f18c9ca21b751a1323019031c94c0bf5ca1d2929ef5913cc56f00aab6e91` | MIT or public domain (at the end of the file) |
| doctest | `doctest/doctest.h` | v2.4.12 | github.com/doctest/doctest at `1da23a3e8119ec5cce4f9388e91b065e20bf06f5` (tag v2.4.12) | `94029a7d32da24a56249658147dbd2b33ff0b9ed665295cbbaf19aafff5b0ced` | MIT (`doctest/LICENSE.txt`) |

Both files are unmodified. stb_image is compiled in its own translation unit
(`src/stb_image_impl.cpp`) without the project's warning flags and without
clang-tidy; its settings (PNG, JPEG and BMP only, no stdio, 16384 px limit)
are in `src/stb_image_config.h`.

ONNX Runtime is not vendored: CMake downloads the official prebuilt release
(see `cmake/onnxruntime.cmake` for the version, URL and SHA-256).
