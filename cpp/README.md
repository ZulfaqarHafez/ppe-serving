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
| | |
|---|---|
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical CPUs (avx2, avx512_vnni, avx512f, avx_vnni, fma) |
| RAM | 15.7 GiB |
| OS | Ubuntu 24.04.5 LTS, kernel 6.18.44-fc-v445 |
| C++ | Ubuntu clang version 18.1.3 (1ubuntu1), Release (-O3 -DNDEBUG), ppe_detect 0.1.0 (onnxruntime 1.29.0) |
| Python | Python 3.13.18, onnxruntime 1.29.0, numpy 2.5.3, Pillow 12.3.0 |
| Run | 2026-11-13T09:43:54+00:00 to 2026-11-13T09:51:42+00:00 (UTC); the 1-minute load average fell under 0.5 after 0 min of waiting |
<!-- END GENERATED: machine -->

### Latency: C++ against Python, int8 model

Same model file, same five images, same ONNX Runtime version (the C++ prebuilt library and the Python wheel are both 1.29.0), same session options. Python's preprocessing is Pillow plus numpy, as in the script behind `samples.json`; its postprocessing is numpy plus a Python NMS loop, as in that script.

<!-- BEGIN GENERATED: latency-int8 -->
**int8, 1 thread.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. System load (1-minute load average, sampled before and after every process) ranged from 0.31 to 0.86 on 4 CPUs. The load average lags by about a minute and counts this benchmark's own processes, so it rises during the run even on an otherwise idle machine.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 6.45 | 6.23 | 9.93 | 13.1 | 9.81 | 9.32 | 14.6 | 17.9 | 1.50x |
| Preprocess (letterbox) | 2.65 | 2.51 | 3.90 | 5.45 | 2.69 | 2.56 | 3.79 | 4.77 | 1.02x |
| Inference (model call) | 72.5 | 72.2 | 88.9 | 98.3 | 71.8 | 72.2 | 87.0 | 102.1 | 1.00x |
| Postprocess (decode, NMS) | 0.026 | 0.028 | 0.043 | 0.065 | 0.324 | 0.312 | 0.440 | 0.550 | 11.28x |
| **End to end** | 81.6 | 81.0 | 99.6 | 112.0 | 84.6 | 83.7 | 101.8 | 118.3 | 1.03x |

**int8, runtime default threads.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. System load (1-minute load average, sampled before and after every process) ranged from 0.85 to 3.20 on 4 CPUs. The load average lags by about a minute and counts this benchmark's own processes, so it rises during the run even on an otherwise idle machine.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 5.82 | 5.50 | 9.04 | 10.5 | 9.08 | 8.55 | 13.5 | 16.9 | 1.55x |
| Preprocess (letterbox) | 2.37 | 2.27 | 3.34 | 4.19 | 2.39 | 2.26 | 3.35 | 4.36 | 0.99x |
| Inference (model call) | 30.3 | 29.4 | 37.5 | 44.6 | 30.7 | 29.6 | 38.9 | 46.0 | 1.01x |
| Postprocess (decode, NMS) | 0.020 | 0.023 | 0.032 | 0.044 | 0.261 | 0.252 | 0.339 | 0.432 | 10.78x |
| **End to end** | 38.5 | 37.6 | 48.0 | 56.1 | 42.5 | 41.1 | 53.7 | 63.3 | 1.09x |
<!-- END GENERATED: latency-int8 -->

### Latency: fp32 model (optional, local only)

<!-- BEGIN GENERATED: latency-fp32 -->
**fp32, 1 thread.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. System load (1-minute load average, sampled before and after every process) ranged from 1.32 to 3.20 on 4 CPUs. The load average lags by about a minute and counts this benchmark's own processes, so it rises during the run even on an otherwise idle machine.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 5.94 | 5.70 | 9.07 | 10.9 | 9.30 | 8.72 | 13.7 | 18.0 | 1.53x |
| Preprocess (letterbox) | 2.42 | 2.30 | 3.52 | 4.64 | 2.50 | 2.35 | 3.44 | 4.49 | 1.02x |
| Inference (model call) | 50.8 | 49.8 | 61.5 | 69.9 | 51.7 | 50.7 | 61.8 | 68.9 | 1.02x |
| Postprocess (decode, NMS) | 0.017 | 0.018 | 0.026 | 0.036 | 0.284 | 0.277 | 0.383 | 0.463 | 15.21x |
| **End to end** | 59.2 | 57.9 | 71.0 | 80.6 | 63.8 | 62.5 | 76.8 | 86.3 | 1.08x |

**fp32, runtime default threads.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. System load (1-minute load average, sampled before and after every process) ranged from 1.32 to 2.90 on 4 CPUs. The load average lags by about a minute and counts this benchmark's own processes, so it rises during the run even on an otherwise idle machine.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 6.52 | 6.02 | 11.1 | 13.1 | 9.29 | 8.87 | 13.7 | 16.9 | 1.47x |
| Preprocess (letterbox) | 2.71 | 2.50 | 4.23 | 5.26 | 2.42 | 2.27 | 3.46 | 4.60 | 0.91x |
| Inference (model call) | 18.9 | 18.3 | 24.3 | 31.7 | 18.3 | 17.2 | 23.5 | 27.2 | 0.94x |
| Postprocess (decode, NMS) | 0.018 | 0.018 | 0.028 | 0.034 | 0.231 | 0.224 | 0.331 | 0.400 | 12.37x |
| **End to end** | 28.2 | 27.2 | 37.9 | 43.7 | 30.2 | 29.2 | 38.8 | 45.5 | 1.08x |
<!-- END GENERATED: latency-fp32 -->

### Cold start and memory

<!-- BEGIN GENERATED: cold-start -->
| Threads | C++ p50 (p95) ms | Python p50 (p95) ms | Python / C++ (p50) | C++ peak RSS MiB | Python peak RSS MiB | Runs each | Background load |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 thread | 156 (194) | 271 (322) | 1.74x | 57.9 | 91.7 | 20 | 2.60 to 2.90 |
| runtime default threads | 133 (157) | 259 (278) | 1.94x | 58.2 | 91.9 | 20 | 2.60 to 2.82 |

Cold start is the time from fork to the first byte of JSON on stdout for one image (`site-backs.png`), so it includes process start, library loading, model load and one detection. Peak RSS is the largest `ru_maxrss` over the runs. Both are read by `bench/launch.py`, whose own resident size (11.7 MiB) is a floor under the RSS figures.
<!-- END GENERATED: cold-start -->

### What the numbers say

The hypothesis going in was that the model call costs the same in both languages and that any C++ gain sits in decoding, pre- and post-processing, cold start and memory. These tables support that, with one correction: preprocessing is not a gain.

- **The model call is the same.** Inference p50 is within a few percent between C++ and Python for both models and both thread settings (the "Python / C++" column). Both call the same ONNX Runtime kernels; the language around the call does not change them.
- **Image decode is faster in C++.** stb_image decodes the PNGs faster than Pillow's open plus `convert("RGB")`, the largest absolute gain per image.
- **Preprocessing is about even.** Pillow's resize is also C, and the C++ port does the same arithmetic, so there is little to gain.
- **Postprocessing is many times faster in C++, but small in both.** It is under a millisecond in Python, so it barely moves the end-to-end time.
- **End to end, C++ is modestly faster per image**, because the model call dominates. The clearer wins are outside the loop: **cold start** (process start to first result) is roughly half in C++, and **peak memory** is lower, since the C++ process does not load the Python interpreter, numpy and Pillow.
- **int8 against fp32 on this CPU:** the int8 model call is slower than fp32 at 1 thread (compare the inference rows of the two 1-thread tables), even though the file is about four times smaller. Dynamic quantization here buys download size, not speed, on this CPU.
- **Noise.** This run started on an idle machine (1-minute load average 0.31) with no other workload during it. The load figure next to each table rises through the run because it includes the benchmark's own processes. Medians are steadier than the p95 and p99 tails on a shared virtual machine.

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
- C++ model call p50, 1 thread: int8 72.2 ms, fp32 49.8 ms (int8 / fp32 = 1.45).
- C++ model call p50, runtime default threads: int8 29.4 ms, fp32 18.3 ms (int8 / fp32 = 1.60).

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
- **Ownership.** `ppe::Detector` owns the ONNX Runtime environment and session and the input and output buffers, behind a pimpl so ONNX Runtime headers stay out of the public API. It is move-only. The model reads from and writes into those buffers directly (the tensors wrap them), so there is no copy in or out. `ppe::Image` owns its pixels in a `std::vector`; `ppe::ImageView` is the non-owning view the pipeline takes. stb_image's buffer is held by a `std::unique_ptr` with `stbi_image_free` as the deleter. There are no raw `new` or `delete` expressions in the code.
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
