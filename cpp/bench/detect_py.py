"""detect_py: the Python twin of ppe_detect for the cold-start measurement.

Loads the model, runs one or more images and prints the same JSON layout as
ppe_detect. bench/run_bench.py times process start to the first byte of this
output, and reads the process's peak resident memory.

Usage: detect_py.py --model PATH [--threads N] IMAGE...
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
import ppe_reference as ref  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.7)
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    sess = ref.session(a.model, a.threads)
    size = sess.get_inputs()[0].shape[2]
    images = []
    for path in a.images:
        img = ref.load_image(path)
        x, box = ref.preprocess(img, size)
        found = ref.postprocess(ref.infer(sess, x), box, a.threshold, a.iou)
        images.append({"file": path, "width": img.size[0], "height": img.size[1],
                       "detections": ref.to_json(found)})
    sys.stdout.write(json.dumps({"model": os.path.basename(a.model), "input_size": size,
                                 "threads": a.threads, "score_threshold": a.threshold,
                                 "iou_threshold": a.iou, "images": images},
                                separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
