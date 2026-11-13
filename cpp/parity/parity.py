"""Parity test: the C++ CLI against Python onnxruntime on the five samples.

For each sample and each thread setting (1 intra-op thread, and the runtime
default) it compares, between ppe_detect (C++) and python/ppe_reference.py:

  input tensor    the [1, 3, 320, 320] float32 model input (from --dump-dir)
  raw output      the [1, 10, 2100] float32 output0 block
  detections      label, score and box after decode and NMS, at 0.25 and 0.5

and, with --reference, checks that both reproduce samples.json (the labels and
the scores rounded to 3 decimals, in order) at both thresholds.

Tolerances (the test fails beyond them): input tensors must be equal; raw
outputs and scores within 1e-6 absolute; box corners within 1e-4 px. The
measured differences are written to --out whatever they are.

Usage: python3 parity/parity.py --cli build/release-clang/ppe_detect \
           --model .cache/models/ppe_yolov8s_320_int8dyn.onnx \
           --reference data/reference/samples.json --out results/parity.json
"""
import argparse
import hashlib
import json
import pathlib
import platform
import subprocess
import sys
import tempfile

import numpy as np
import onnxruntime as ort
import PIL

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
import ppe_reference as ref  # noqa: E402

SAMPLES = ["site-backs", "rooftop-cctv", "plant-cctv", "hi-vis-walk", "packing-cctv"]
THRESHOLDS = [0.25, 0.5]
THREADS = [1, 0]
TOL_OUTPUT = 1e-6
TOL_SCORE = 1e-6
TOL_BOX = 1e-4


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(cli, model, images, threads, threshold, dump=None):
    cmd = [cli, "--model", model, "--threads", str(threads), "--threshold", str(threshold)]
    if dump:
        cmd += ["--dump-dir", dump]
    res = subprocess.run(cmd + [str(p) for p in images], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"ppe_detect failed ({res.returncode}): {res.stderr}")
    return json.loads(res.stdout)


def compare_detections(cpp, py):
    """Pair detections in order; the lists must have the same labels in order."""
    labels_equal = [d["label"] for d in cpp] == [d["label"] for d in py]
    score_diff = box_diff = 0.0
    if labels_equal:
        for c, p in zip(cpp, py):
            score_diff = max(score_diff, abs(c["score"] - p["score"]))
            box_diff = max(box_diff, max(abs(a - b) for a, b in zip(c["box"], p["box"])))
    return {"count_cpp": len(cpp), "count_python": len(py), "labels_equal": labels_equal,
            "max_score_diff": score_diff, "max_box_diff_px": box_diff,
            "bit_identical": labels_equal and score_diff == 0.0 and box_diff == 0.0}


def reference_rows(reference, sid, threshold):
    sample = next(s for s in reference["samples"] if s["id"] == sid)
    return [(d["label"], d["score"]) for d in sample["at"][str(threshold)]["detections"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--samples", default=str(HERE.parent / "data" / "samples"))
    ap.add_argument("--reference", help="samples.json to reproduce (int8 model only)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    model = pathlib.Path(a.model)
    images = [pathlib.Path(a.samples) / f"{sid}.png" for sid in SAMPLES]
    reference = json.loads(pathlib.Path(a.reference).read_text()) if a.reference else None
    cli_version = subprocess.run([a.cli, "--version"], capture_output=True, text=True).stdout.strip()

    report = {
        "generated_by": "parity/parity.py",
        "model": {"file": model.name, "sha256": sha256(model)},
        "cpp": cli_version,
        "python": {"version": platform.python_version(), "onnxruntime": ort.__version__,
                   "numpy": np.__version__, "pillow": PIL.__version__},
        "tolerances": {"input": 0.0, "output_abs": TOL_OUTPUT, "score_abs": TOL_SCORE,
                       "box_px": TOL_BOX},
        "runs": [],
    }
    ok = True
    for threads in THREADS:
        sess = ref.session(str(model), threads)
        with tempfile.TemporaryDirectory() as dump:
            cpp = {t: run_cli(a.cli, str(model), images, threads, t, dump if t == THRESHOLDS[0]
                              else None) for t in THRESHOLDS}
            for i, (sid, path) in enumerate(zip(SAMPLES, images)):
                x, box = ref.preprocess(ref.load_image(str(path)), 320)
                out = ref.infer(sess, x)
                cin = np.fromfile(pathlib.Path(dump) / f"{sid}.input.f32", dtype="<f4")
                cout = np.fromfile(pathlib.Path(dump) / f"{sid}.output.f32", dtype="<f4")
                pin, pout = x.reshape(-1), out.reshape(-1)
                row = {
                    "sample": sid,
                    "threads": threads,
                    "input": {"elements": int(pin.size),
                              "equal": bool(cin.shape == pin.shape and np.array_equal(cin, pin)),
                              "max_abs_diff": float(np.max(np.abs(cin - pin)))},
                    "output": {"elements": int(pout.size),
                               "bit_identical": bool(cout.tobytes() == pout.tobytes()),
                               "differing_elements": int(np.count_nonzero(cout != pout)),
                               "max_abs_diff": float(np.max(np.abs(cout - pout)))},
                    "detections": {},
                }
                for t in THRESHOLDS:
                    py = ref.to_json(ref.postprocess(out, box, t))
                    c = cpp[t]["images"][i]["detections"]
                    cmp = compare_detections(c, py)
                    if reference is not None:
                        want = reference_rows(reference, sid, t)
                        cmp["reproduces_reference_cpp"] = [
                            (d["label"], round(d["score"], 3)) for d in c] == want
                        cmp["reproduces_reference_python"] = [
                            (d["label"], round(d["score"], 3)) for d in py] == want
                        cmp["reference"] = [f"{label} {score:.3f}" for label, score in want]
                    cmp["cpp"] = [f"{d['label']} {d['score']:.3f}" for d in c]
                    row["detections"][str(t)] = cmp
                    passed = (cmp["labels_equal"] and cmp["max_score_diff"] <= TOL_SCORE
                              and cmp["max_box_diff_px"] <= TOL_BOX
                              and cmp.get("reproduces_reference_cpp", True)
                              and cmp.get("reproduces_reference_python", True))
                    ok = ok and passed
                ok = ok and row["input"]["equal"] and row["output"]["max_abs_diff"] <= TOL_OUTPUT
                report["runs"].append(row)
                print(f"threads={threads} {sid:13s} input equal={row['input']['equal']} "
                      f"output max|diff|={row['output']['max_abs_diff']:.3g} "
                      f"bit-identical={row['output']['bit_identical']} "
                      + " ".join(f"@{t}: {len(row['detections'][str(t)]['cpp'])} dets "
                                 f"max|dscore|={row['detections'][str(t)]['max_score_diff']:.3g}"
                                 for t in THRESHOLDS))

    runs = report["runs"]
    dets = [d for r in runs for d in r["detections"].values()]
    report["summary"] = {
        "passed": ok,
        "comparisons": len(runs),
        "inputs_equal": sum(r["input"]["equal"] for r in runs),
        "outputs_bit_identical": sum(r["output"]["bit_identical"] for r in runs),
        "max_output_abs_diff": max(r["output"]["max_abs_diff"] for r in runs),
        "detection_lists": len(dets),
        "detection_lists_bit_identical": sum(d["bit_identical"] for d in dets),
        "max_score_diff": max(d["max_score_diff"] for d in dets),
        "max_box_diff_px": max(d["max_box_diff_px"] for d in dets),
        "detections_compared": sum(d["count_cpp"] for d in dets),
    }
    if reference is not None:
        report["summary"]["reference_lists"] = len(dets)
        report["summary"]["reference_reproduced_cpp"] = sum(d["reproduces_reference_cpp"] for d in dets)
        report["summary"]["reference_reproduced_python"] = sum(
            d["reproduces_reference_python"] for d in dets)
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["summary"], indent=1))
    print("PARITY", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
