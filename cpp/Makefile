# Shortcuts over the CMake presets and the Python scripts. Run from cpp/.
# Every target is a thin wrapper; the commands are what CI runs.

PYTHON ?= python3
CLANG_FORMAT ?= clang-format
PRESET ?= release-clang
BUILD := build/$(PRESET)
MODEL := .cache/models/ppe_yolov8s_320_int8dyn.onnx
FP32_MODEL := .cache/models/ppe_yolov8s_320_fp32.onnx
FORMAT_FILES := $(shell find include src tools bench tests -name '*.cpp' -o -name '*.hpp' -o -name '*.h')

.PHONY: all build test test-gcc asan parity bench tidy format format-check readme readme-check fp32 clean

all: build

## build: configure and build the release-clang preset (downloads ONNX Runtime and the model once)
build:
	cmake --preset $(PRESET)
	cmake --build --preset $(PRESET)

## test: unit, detector and CLI exit-code tests with clang and with GCC
test:
	$(MAKE) build PRESET=release-clang
	ctest --preset release-clang
	$(MAKE) build PRESET=release-gcc
	ctest --preset release-gcc

## asan: the same tests under AddressSanitizer and UndefinedBehaviorSanitizer (GCC)
asan:
	cmake --preset asan
	cmake --build --preset asan
	ctest --preset asan

## parity: compare the C++ pipeline with Python onnxruntime on the five samples
parity: build
	$(PYTHON) parity/parity.py --cli $(BUILD)/ppe_detect --model $(MODEL) \
		--reference data/reference/samples.json --out results/parity.json
	@if [ -f $(FP32_MODEL) ]; then \
		$(PYTHON) parity/parity.py --cli $(BUILD)/ppe_detect --model $(FP32_MODEL) \
			--out results/parity_fp32.json; \
	else echo "fp32 model not present: skipping its parity run (see 'make fp32')"; fi

## bench: C++ against Python latency, cold start and memory (waits for a quiet machine)
bench: build
	$(PYTHON) bench/run_bench.py --cli $(BUILD)/ppe_detect --bench $(BUILD)/ppe_bench \
		--model $(MODEL) $(if $(wildcard $(FP32_MODEL)),--fp32-model $(FP32_MODEL)) \
		--out results/bench.json
	$(MAKE) readme

## tidy: build with clang-tidy, every warning an error
tidy:
	cmake --preset tidy
	cmake --build --preset tidy

## format: rewrite the sources with clang-format
format:
	$(CLANG_FORMAT) -i $(FORMAT_FILES)

## format-check: fail if any source is not clang-formatted
format-check:
	$(CLANG_FORMAT) --dry-run --Werror $(FORMAT_FILES)

## readme: render the README tables from results/*.json
readme:
	$(PYTHON) scripts/render_readme.py

## readme-check: fail if the README tables differ from results/*.json
readme-check:
	$(PYTHON) scripts/render_readme.py --check

## fp32: export the optional fp32 320 px model from the published weights (needs torch)
fp32:
	$(PYTHON) scripts/export_fp32.py --out $(FP32_MODEL)

clean:
	rm -rf build
