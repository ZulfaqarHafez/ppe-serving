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
| Run | 2026-11-13T08:53:37+00:00 to 2026-11-13T09:16:15+00:00 (UTC); the 1-minute load average fell under 0.5 after 13 min of waiting |
<!-- END GENERATED: machine -->

### Latency: C++ against Python, int8 model

Same model file, same five images, same ONNX Runtime version (the C++ prebuilt library and the Python wheel are both 1.29.0), same session options. Python's preprocessing is Pillow plus numpy, as in the script behind `samples.json`; its postprocessing is numpy plus a Python NMS loop, as in that script.

<!-- BEGIN GENERATED: latency-int8 -->
**int8, 1 thread.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. Background load (1-minute load average, sampled before and after every process) ranged from 0.38 to 3.98 on 4 CPUs. Another workload was running on the machine during part of this table; with one inference thread the effect is smaller, but the tails (p95, p99) are less reliable than the medians.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 6.64 | 6.14 | 11.5 | 13.2 | 10.2 | 9.41 | 15.9 | 18.7 | 1.53x |
| Preprocess (letterbox) | 2.78 | 2.52 | 4.78 | 5.67 | 2.84 | 2.63 | 4.34 | 5.01 | 1.04x |
| Inference (model call) | 75.2 | 70.5 | 98.5 | 110.2 | 76.3 | 70.9 | 103.3 | 113.4 | 1.00x |
| Postprocess (decode, NMS) | 0.025 | 0.028 | 0.042 | 0.057 | 0.328 | 0.314 | 0.448 | 0.539 | 11.39x |
| **End to end** | 84.7 | 79.9 | 112.5 | 124.8 | 89.7 | 84.7 | 118.9 | 131.1 | 1.06x |

**int8, runtime default threads.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. Background load (1-minute load average, sampled before and after every process) ranged from 3.93 to 6.16 on 4 CPUs. Another workload was running on the machine during part of this table, so these multi-thread numbers are noisy: they compete with it for cores.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 7.61 | 6.32 | 13.4 | 25.9 | 11.9 | 9.91 | 22.1 | 34.2 | 1.57x |
| Preprocess (letterbox) | 3.11 | 2.60 | 6.00 | 9.49 | 3.33 | 2.80 | 5.76 | 12.2 | 1.08x |
| Inference (model call) | 52.7 | 40.8 | 121.4 | 167.6 | 54.4 | 41.9 | 117.4 | 177.5 | 1.03x |
| Postprocess (decode, NMS) | 0.037 | 0.027 | 0.042 | 0.067 | 0.390 | 0.307 | 0.482 | 1.46 | 11.52x |
| **End to end** | 63.5 | 50.9 | 140.7 | 195.2 | 70.0 | 56.3 | 138.2 | 222.6 | 1.11x |
<!-- END GENERATED: latency-int8 -->

### Latency: fp32 model (optional, local only)

<!-- BEGIN GENERATED: latency-fp32 -->
**fp32, 1 thread.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. Background load (1-minute load average, sampled before and after every process) ranged from 2.50 to 4.43 on 4 CPUs. Another workload was running on the machine during part of this table; with one inference thread the effect is smaller, but the tails (p95, p99) are less reliable than the medians.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 6.61 | 6.14 | 11.4 | 13.1 | 10.2 | 9.35 | 16.8 | 18.4 | 1.52x |
| Preprocess (letterbox) | 2.78 | 2.53 | 4.80 | 5.44 | 2.87 | 2.64 | 4.46 | 4.97 | 1.05x |
| Inference (model call) | 56.5 | 53.2 | 71.7 | 81.8 | 57.5 | 53.7 | 73.8 | 88.2 | 1.01x |
| Postprocess (decode, NMS) | 0.019 | 0.019 | 0.030 | 0.042 | 0.320 | 0.304 | 0.447 | 0.494 | 15.90x |
| **End to end** | 66.0 | 62.8 | 85.3 | 95.3 | 70.8 | 67.1 | 91.1 | 103.5 | 1.07x |

**fp32, runtime default threads.** 800 timed iterations per language (8 alternating rounds of 100, after 20 untimed warm-up iterations in each process), cycling through the five samples. Background load (1-minute load average, sampled before and after every process) ranged from 2.50 to 3.94 on 4 CPUs. Another workload was running on the machine during part of this table, so these multi-thread numbers are noisy: they compete with it for cores.

| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | Python p50 | Python p95 | Python p99 | Python / C++ (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Image decode | 7.50 | 6.30 | 14.4 | 21.8 | 12.6 | 11.0 | 25.0 | 32.1 | 1.75x |
| Preprocess (letterbox) | 3.26 | 2.64 | 6.96 | 10.6 | 3.56 | 3.03 | 7.53 | 10.1 | 1.15x |
| Inference (model call) | 29.4 | 22.4 | 73.3 | 115.6 | 33.3 | 23.0 | 86.9 | 121.7 | 1.03x |
| Postprocess (decode, NMS) | 0.020 | 0.019 | 0.030 | 0.048 | 0.377 | 0.281 | 0.452 | 4.28 | 14.62x |
| **End to end** | 40.2 | 32.9 | 93.5 | 132.4 | 49.8 | 38.1 | 115.7 | 150.9 | 1.16x |
<!-- END GENERATED: latency-fp32 -->

### Cold start and memory

<!-- BEGIN GENERATED: cold-start -->
| Threads | C++ p50 (p95) ms | Python p50 (p95) ms | Python / C++ (p50) | C++ peak RSS MiB | Python peak RSS MiB | Runs each | Background load |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 thread | 186 (233) | 405 (457) | 2.17x | 58.8 | 91.8 | 20 | 3.30 to 3.75 |
| runtime default threads | 269 (375) | 500 (578) | 1.86x | 59.3 | 92.1 | 20 | 3.30 to 3.45 |

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
- **Noise.** The machine was quiet when the run started, but another builder's workload returned partway through (the load is recorded next to each table). The 1-thread medians are the most trustworthy figures here; the default-thread rows and all p95 and p99 values are noisy.

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
- C++ model call p50, 1 thread: int8 70.5 ms, fp32 53.2 ms (int8 / fp32 = 1.33).
- C++ model call p50, runtime default threads: int8 40.8 ms, fp32 22.4 ms (int8 / fp32 = 1.82).

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
