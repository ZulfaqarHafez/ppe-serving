# cpp: the PPE detector in C++17

A standalone C++17 library and command-line tool that runs the repository's PPE detector (YOLOv8s, exported to ONNX at 320 px with dynamic int8 weights) on still images: decode the image, letterbox it, run ONNX Runtime, decode the output, apply per-class non-maximum suppression and print JSON. It is checked against the Python pipeline that produced the site's reference results, and benchmarked against Python on the same model, images and thread settings.

Built by Zulfaqar Hafez with Claude Code as the coding agent.

## Build and run

On Linux x86_64 with CMake 3.27 or newer, Ninja and clang 18 (or GCC 13):

```sh
cd cpp
make build      # downloads ONNX Runtime 1.29.0 and the model once (both SHA-256 checked), builds
./build/release-clang/ppe_detect data/samples/plant-cctv.png
```

```json
{"model":"ppe_yolov8s_320_int8dyn.onnx","input_size":320,"threads":0,"score_threshold":0.25,"iou_threshold":0.7,
 "images":[{"file":"data/samples/plant-cctv.png","width":640,"height":640,"detections":[
  {"label":"No-vest","class_id":4,"score":S,"box":[x1,y1,x2,y2]}, ...]}]}
```

(Reformatted here; the tool prints one line, with boxes in original image pixels and numbers in their shortest round-trip form.)

Options: `--model PATH`, `--threshold T` (default 0.25), `--iou I` (default 0.7), `--threads N` (0 is the ONNX Runtime default), `--dump-dir DIR` (also writes each image's input tensor and raw output as float32 files), `--help`, `--version`.

| Exit code | Meaning |
|---|---|
| 0 | success |
| 1 | unexpected error |
| 2 | usage error (unknown option, value out of range, no image) |
| 3 | an image is missing, unreadable or not a PNG, JPEG or BMP |
| 4 | the model is missing, invalid, or not float [1, 3, S, S] in and [1, 10, N] out |
| 5 | inference failed |
| 6 | writing a `--dump-dir` file failed |

Other targets: `make test` (clang and GCC), `make asan`, `make tidy`, `make format-check`, `make parity`, `make bench`, `make fp32` (optional fp32 model, below).

## Results

All numbers below are rendered by `scripts/render_readme.py` from the JSON files in [`results/`](results/), which the scripts named there wrote. `make readme-check` (run in CI) fails if the two disagree.

### Machine

<!-- BEGIN GENERATED: machine -->
<!-- END GENERATED: machine -->

### Latency: C++ against Python, int8 model

Same model file, same five images, same ONNX Runtime version (the C++ prebuilt library and the Python wheel are both 1.29.0), same session options. Python's preprocessing is Pillow plus numpy, as in the script behind `samples.json`; its postprocessing is numpy plus a Python NMS loop, as in that script.

<!-- BEGIN GENERATED: latency-int8 -->
<!-- END GENERATED: latency-int8 -->

### Latency: fp32 model (optional, local only)

<!-- BEGIN GENERATED: latency-fp32 -->
<!-- END GENERATED: latency-fp32 -->

### Cold start and memory

<!-- BEGIN GENERATED: cold-start -->
<!-- END GENERATED: cold-start -->

### What the numbers say

INTERPRETATION

### Parity with Python

`parity/parity.py` runs `ppe_detect --dump-dir` and `python/ppe_reference.py` (Pillow, numpy, onnxruntime 1.29.0 from [`python/requirements.txt`](python/requirements.txt)) on the five samples with 1 thread and with the default, and compares the input tensors, the raw outputs, and the scores and boxes after NMS at thresholds 0.25 and 0.5. Tolerances, stated before measuring: input tensors equal; raw outputs and scores within 1e-6; boxes within 1e-4 px. It also checks that both reproduce [`data/reference/samples.json`](data/reference/samples.json), the site's reference run.

<!-- BEGIN GENERATED: parity -->
- Comparisons: 10 (5 samples x 2 thread settings) on `ppe_yolov8s_320_int8dyn.onnx`, ppe_detect 0.1.0 (onnxruntime 1.29.0) against Python 3.13.18 with onnxruntime 1.29.0.
- Input tensors equal: 10 of 10.
- Raw outputs bit-identical: 10 of 10; largest absolute difference 0 (tolerance 1e-06).
- Detection lists (thresholds 0.25 and 0.5): 20 of 20 identical in label, score and box, 52 detections in all; largest score difference 0 (tolerance 1e-06), largest box difference 0 px (tolerance 0.0001 px).
- `samples.json` reproduced (labels and scores to 3 decimals, in order): C++ 20 of 20 lists, Python 20 of 20.
- Result: passed.

| Sample | C++ at 0.25 | C++ at 0.5 | samples.json at 0.25 |
|---|---|---|---|
| site-backs | Vest 0.553, Vest 0.524, Vest 0.515, Helmet 0.259, Helmet 0.256 | Vest 0.553, Vest 0.524, Vest 0.515 | Vest 0.553, Vest 0.524, Vest 0.515, Helmet 0.259, Helmet 0.256 |
| rooftop-cctv | No-Helmet 0.600, No-vest 0.566, No-vest 0.513, Helmet 0.298 | No-Helmet 0.600, No-vest 0.566, No-vest 0.513 | No-Helmet 0.600, No-vest 0.566, No-vest 0.513, Helmet 0.298 |
| plant-cctv | No-vest 0.694, No-Helmet 0.627 | No-vest 0.694, No-Helmet 0.627 | No-vest 0.694, No-Helmet 0.627 |
| hi-vis-walk | Vest 0.514, Vest 0.493, No-Helmet 0.460, Helmet 0.328, Vest 0.309 | Vest 0.514 | Vest 0.514, Vest 0.493, No-Helmet 0.460, Helmet 0.328, Vest 0.309 |
| packing-cctv | Gloves 0.399 | none | Gloves 0.399 |
<!-- END GENERATED: parity -->

### int8 against fp32

The course project's evaluation notes say where the weights live and how the 320 px export was made, so `scripts/export_fp32.py` repeats it on CPU, in seconds, from the published checkpoint, pinned by Hugging Face revision and SHA-256, and pins the SHA-256 of its output (it removes Ultralytics' export timestamp so the file is reproducible). The fp32 file stays local and is not hosted; CI covers int8 only. `make parity` and `make bench` include it when it is present.

<!-- BEGIN GENERATED: quantization -->
- Size: fp32 44.63 MB, int8 11.37 MB (3.93x smaller).
- Provenance check: re-quantizing the reproduced fp32 export with onnxruntime 1.29.0 (`quantize_dynamic, QuantType.QUInt8`) gives 11,366,723 bytes against the served file's 11,366,765 (which also carries a 32-character export `date` that the reproduced export drops); 318 of 332 initializers are identical. Of the rest, 13 float32 weight scales differ by at most 1.1e-07 relative (float32 machine epsilon is 1.19e-07); 1 quantized weight tensor(s) differ in 2 element(s) by at most 1 quantization step(s).

| Sample | int8 at 0.25 | fp32 at 0.25 |
|---|---|---|
| site-backs | Vest 0.553, Vest 0.524, Vest 0.515, Helmet 0.259, Helmet 0.256 | Vest 0.563, Vest 0.517, Vest 0.510, Helmet 0.274 |
| rooftop-cctv | No-Helmet 0.600, No-vest 0.566, No-vest 0.513, Helmet 0.298 | No-Helmet 0.583, No-vest 0.539, No-vest 0.469, Helmet 0.327 |
| plant-cctv | No-vest 0.694, No-Helmet 0.627 | No-vest 0.672, No-Helmet 0.595 |
| hi-vis-walk | Vest 0.514, Vest 0.493, No-Helmet 0.460, Helmet 0.328, Vest 0.309 | Vest 0.497, Vest 0.473, No-Helmet 0.466, Vest 0.322, Helmet 0.281, No-Helmet 0.255 |
| packing-cctv | Gloves 0.399 | Gloves 0.407 |
<!-- END GENERATED: quantization -->

## Design notes

- **Where the code came from.** The letterbox, the Pillow-exact resize, the decode and the NMS are adapted from the C++ port in [`ros2/src/ppe_detector`](../ros2/src/ppe_detector) (written for the ROS 2 node), which ports `ppeDetect.ts` on the site. Here they are a standalone library with no ROS, OpenCV or other runtime dependency besides ONNX Runtime.
- **Ownership.** `ppe::Detector` owns the ONNX Runtime environment and session and the input and output buffers, behind a pimpl so ONNX Runtime headers stay out of the public API. It is move-only. The model reads from and writes into those buffers directly (the tensors wrap them), so there is no copy in or out. `ppe::Image` owns its pixels in a `std::vector`; `ppe::ImageView` is the non-owning view the pipeline takes. stb_image's buffer is held by a `std::unique_ptr` with `stbi_image_free` as the deleter. There is no `new` or `delete` in the code.
- **Error handling.** One exception type, `ppe::Error`, carries an `ErrorCode` (invalid argument, image read, model load, inference, I/O). ONNX Runtime exceptions are caught at the boundary and rethrown as `ppe::Error`; the CLI maps each code to one exit code.
- **Why stb_image.** One vendored header at a pinned commit and no system packages. For PNG it produces the same RGB bytes as Pillow (the unit tests and the parity test check this); JPEG decoders can differ slightly between libraries, so the parity inputs are PNG. It cannot read WebP, so the five WebP samples were converted to lossless PNG (`scripts/convert_samples.py` checks the pixels are unchanged). It runs in its own translation unit, without the project's warning flags and clang-tidy.
- **Why the resize is a Pillow port.** The reference results were made with Pillow's `Image.resize(..., BILINEAR)`, which, when shrinking, averages over the whole source footprint with fixed-point weights. A plain 2x2 bilinear lookup (OpenCV's default `INTER_LINEAR`, for example) gives different pixels and so different scores. Porting Pillow's `Resample.c` arithmetic makes the input tensor equal, element for element, which the parity test checks.
- **Thread settings.** `--threads 1` sets ONNX Runtime's intra-op and inter-op pools to 1; `--threads 0` leaves both at the runtime default (ONNX Runtime sizes the intra-op pool from the number of cores). The Python side applies the same rule, so each comparison uses matched settings.
- **Rounding.** The resized side is rounded half up, as `Math.round` in `ppeDetect.ts`; the Python script behind `samples.json` used `round()`, which rounds halves to even. None of the five samples hits a half, and the unit tests pin the half-up case.

## Tests and checks

- **Unit tests** (doctest, vendored): letterbox arithmetic and rounding, the resize against Pillow golden values (shrink, enlarge, one axis unchanged; generated by `tests/make_golden.py`), stride handling, the tensor layout and padding, candidate decode and clamping, IoU, NMS (per class, limit inclusive, stable ties, threshold), JSON escaping and number formatting, image decoding (RGB, grey, RGBA, truncated and junk input, missing files, directories).
- **Detector tests** load the real model: shapes, bad model files, deterministic output, a detection on a sample.
- **CLI tests** (`tests/cli_exit_codes.sh`) check every exit code above and the JSON and dump outputs.
- **Sanitizers.** The same tests run under AddressSanitizer and UndefinedBehaviorSanitizer with GCC (`make asan`; in this sandbox clang has no sanitizer runtime installed). They are clean with one LeakSanitizer suppression, for the prebuilt `libonnxruntime.so`, which leaves one small allocation from inside the library unfreed at exit (listed with its reason in [`sanitizers/lsan.supp`](sanitizers/lsan.supp)). Nothing in the project's own code is suppressed.
- **Static checks.** Warnings are errors on clang and GCC (`-Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wold-style-cast` and more). `make tidy` builds with clang-tidy, every warning an error; the disabled checks are listed with reasons in [`.clang-tidy`](.clang-tidy). `make format-check` runs clang-format.
- **CI** ([`.github/workflows/cpp.yml`](../.github/workflows/cpp.yml)): build and test with clang and GCC, ASan and UBSan, the parity test with the Python side from the pinned requirements file, the README check, clang-format and clang-tidy.

## Reproduce

```sh
cd cpp
make test asan tidy format-check            # build and check everything
pip install -r python/requirements.txt      # Python 3.13: onnxruntime, numpy, Pillow (pinned)
make parity                                 # writes results/parity.json (and parity_fp32.json if present)
make bench                                  # waits for a quiet machine, writes results/bench.json, re-renders this README
```

The optional fp32 model needs PyTorch and Ultralytics, in a separate virtual environment:

```sh
pip install -r scripts/requirements-fp32.txt --extra-index-url https://download.pytorch.org/whl/cpu
python scripts/export_fp32.py --out .cache/models/ppe_yolov8s_320_fp32.onnx \
    --compare-int8 .cache/models/ppe_yolov8s_320_int8dyn.onnx    # writes results/fp32_export.json
```

## Layout

| Path | What |
|---|---|
| `include/ppe/`, `src/` | the library: `image` (stb decode), `preprocess` (letterbox, Pillow resize), `postprocess` (decode, NMS), `detector` (ONNX Runtime), `json`, `error` |
| `tools/ppe_detect.cpp` | the CLI |
| `tests/` | doctest unit and detector tests, the CLI exit-code script, the golden-value generator |
| `python/` | the Python reference pipeline and its pinned requirements |
| `parity/parity.py` | the parity test |
| `bench/` | `ppe_bench.cpp` and `bench_py.py` (stage timers), `detect_py.py` (Python CLI for cold start), `launch.py`, `run_bench.py` (driver) |
| `scripts/` | sample conversion, fp32 export, README rendering |
| `cmake/` | pinned downloads of ONNX Runtime and the model |
| `data/` | the five samples (CC BY 4.0, see [data/README.md](data/README.md)) and the reference results |
| `results/` | committed result JSON |
| `third_party/` | stb_image and doctest at pinned commits ([third_party/README.md](third_party/README.md)) |

## Limits

- CPU only, on one virtual machine (details above) with no GPU; the numbers would differ on other hardware, and the default-thread numbers depend on what else the machine was running (the background load is recorded next to each table).
- One model at one input size, and five images. Parity on five images shows the two pipelines compute the same thing on those images; it is not an accuracy evaluation. The model's measured accuracy and failures are written up on the site.
- Linux x86_64 only: the build fetches the linux-x64 ONNX Runtime release.
- Batch size 1, one image at a time; no video, no GPU execution provider, no INT8 static quantization or other model changes were tried here.
- The CLI reads PNG, JPEG and BMP (stb_image), not WebP.

## Credits

Model trained by teammates in a university course project with Ultralytics YOLOv8 (AGPL-3.0); dataset CC BY 4.0. See [NOTICE](NOTICE). No licence has been chosen for this code yet, so none is granted.
