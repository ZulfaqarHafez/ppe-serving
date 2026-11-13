#!/usr/bin/env bash
# Checks ppe_detect's documented exit codes.
# Usage: cli_exit_codes.sh PPE_DETECT MODEL SAMPLES_DIR
set -u
cli=$1 model=$2 samples=$3
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

expect() {
  local want=$1 name=$2
  shift 2
  "$@" >"$work/out" 2>"$work/err"
  local got=$?
  if [[ $got -ne $want ]]; then
    echo "FAIL $name: exit $got, expected $want"
    sed 's/^/  stderr: /' "$work/err"
    failures=$((failures + 1))
  else
    echo "ok   $name (exit $got)"
  fi
}

printf 'not an image' >"$work/junk.png"
printf 'not a model' >"$work/junk.onnx"
: >"$work/empty.png"
touch "$work/blocker"

expect 0 "help" "$cli" --help
expect 0 "version" "$cli" --version
expect 0 "one image" "$cli" --model "$model" "$samples/site-backs.png"
expect 0 "two images, one thread" "$cli" --model "$model" --threads 1 \
  "$samples/site-backs.png" "$samples/packing-cctv.png"
expect 2 "no arguments" "$cli"
expect 2 "no image" "$cli" --model "$model"
expect 2 "unknown option" "$cli" --model "$model" --bogus "$samples/site-backs.png"
expect 2 "threshold above 1" "$cli" --model "$model" --threshold 1.5 "$samples/site-backs.png"
expect 2 "threshold not a number" "$cli" --model "$model" --threshold abc "$samples/site-backs.png"
expect 2 "iou missing its value" "$cli" --model "$model" "$samples/site-backs.png" --iou
expect 2 "negative threads" "$cli" --model "$model" --threads -2 "$samples/site-backs.png"
expect 3 "missing image" "$cli" --model "$model" "$work/none.png"
expect 3 "not an image" "$cli" --model "$model" "$work/junk.png"
expect 3 "empty file" "$cli" --model "$model" "$work/empty.png"
expect 3 "a directory" "$cli" --model "$model" "$samples"
expect 4 "missing model" "$cli" --model "$work/none.onnx" "$samples/site-backs.png"
expect 4 "not a model" "$cli" --model "$work/junk.onnx" "$samples/site-backs.png"
expect 6 "dump dir blocked by a file" "$cli" --model "$model" --dump-dir "$work/blocker/sub" \
  "$samples/site-backs.png"

# The success output is one JSON document with the expected fields.
"$cli" --model "$model" "$samples/plant-cctv.png" >"$work/out.json"
for field in '"model":"' '"input_size":320' '"images":[' '"label":"No-vest"' '"box":['; do
  if ! grep -qF "$field" "$work/out.json"; then
    echo "FAIL output lacks $field"
    failures=$((failures + 1))
  fi
done
if command -v python3 >/dev/null && ! python3 -m json.tool "$work/out.json" >/dev/null; then
  echo "FAIL output is not valid JSON"
  failures=$((failures + 1))
fi

# --dump-dir writes the tensors at the expected sizes.
"$cli" --model "$model" --dump-dir "$work/dump" "$samples/plant-cctv.png" >/dev/null
[[ $(stat -c %s "$work/dump/plant-cctv.input.f32") -eq $((3 * 320 * 320 * 4)) ]] ||
  { echo "FAIL input dump size"; failures=$((failures + 1)); }
[[ $(stat -c %s "$work/dump/plant-cctv.output.f32") -eq $((10 * 2100 * 4)) ]] ||
  { echo "FAIL output dump size"; failures=$((failures + 1)); }

echo "$failures failure(s)"
[[ $failures -eq 0 ]]
