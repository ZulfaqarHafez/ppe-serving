"""bench_py: time each stage of the Python pipeline and print the raw samples
as JSON. The Python twin of bench/ppe_bench.cpp; bench/run_bench.py runs the
two alternately and computes the statistics.

Usage: bench_py.py --model PATH --threads N --warmup W --iterations K IMAGE...
Iteration i uses IMAGE[i % count]. Stages, each timed with perf_counter_ns:
  decode       Image.open(path).convert("RGB")
  preprocess   Pillow bilinear letterbox, float32 CHW tensor
  inference    InferenceSession.run
  postprocess  numpy candidate decode and per-class NMS
  end_to_end   all four, timed as one span
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
import onnxruntime as ort  # noqa: E402
import ppe_reference as ref  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()

    sess = ref.session(a.model, a.threads)
    size = sess.get_inputs()[0].shape[2]
    clock = time.perf_counter_ns
    stages = {k: [] for k in ("decode", "preprocess", "inference", "postprocess", "end_to_end")}
    detections = 0
    for i in range(a.warmup + a.iterations):
        path = a.images[i % len(a.images)]
        t0 = clock()
        img = ref.load_image(path)
        t1 = clock()
        x, box = ref.preprocess(img, size)
        t2 = clock()
        out = ref.infer(sess, x)
        t3 = clock()
        found = ref.postprocess(out, box, 0.25, 0.7)
        t4 = clock()
        if i < a.warmup:
            continue
        detections += len(found)
        for k, (s, e) in zip(stages, ((t0, t1), (t1, t2), (t2, t3), (t3, t4), (t0, t4))):
            stages[k].append((e - s) / 1e6)
    print(json.dumps({"language": "python", "onnxruntime": ort.__version__, "threads": a.threads,
                      "warmup": a.warmup, "iterations": a.iterations, "detections": detections,
                      "stages_ms": stages}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
