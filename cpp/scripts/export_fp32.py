"""Export the optional fp32 320 px ONNX model from the published PyTorch weights.

The int8 model the site serves was made from an fp32 320 px export of the
deployed checkpoint, best_deep.pt (Hugging Face repository
iMaximusiV/yolo-ppe-detector), with Ultralytics' ONNX exporter at opset 12,
static batch 1, no NMS in the graph and simplify=True. This script repeats
that export on CPU so the C++ and Python pipelines can also be compared on
fp32. Nothing it produces is committed or hosted.

The checkpoint is fetched from a pinned Hugging Face revision and checked
against a pinned SHA-256. Ultralytics stamps the export time into the ONNX
metadata ("date"); it is removed so the output is byte-for-byte reproducible,
and the result is checked against FP32_SHA256 below.

Usage (in a separate virtual environment, see scripts/requirements-fp32.txt):
  pip install -r scripts/requirements-fp32.txt \\
      --extra-index-url https://download.pytorch.org/whl/cpu
  python3 scripts/export_fp32.py --out .cache/models/ppe_yolov8s_320_fp32.onnx
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import sys
import tempfile
import urllib.request

REVISION = "212555357a34d9058cab905c71f43448c0f079fa"
WEIGHTS_URL = f"https://huggingface.co/iMaximusiV/yolo-ppe-detector/resolve/{REVISION}/best_deep.pt"
WEIGHTS_SHA256 = "f1d1422e135d06b6b866b2ba0b25c519ff7d0179023b0aa5b3b1571898217c16"
FP32_SHA256 = "a1d0659510140172deed05a2aede20b4899a1026b5cbe21fdbb8b03c235923d0"
IMGSZ = 320
OPSET = 12


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_weights(cache: pathlib.Path) -> pathlib.Path:
    path = cache / "best_deep.pt"
    if not path.exists() or sha256(path) != WEIGHTS_SHA256:
        cache.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        print(f"downloading {WEIGHTS_URL}")
        with urllib.request.urlopen(WEIGHTS_URL) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        got = sha256(part)
        if got != WEIGHTS_SHA256:
            part.unlink()
            sys.exit(f"best_deep.pt has SHA-256 {got}, expected {WEIGHTS_SHA256}")
        part.rename(path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--cache", type=pathlib.Path, default=pathlib.Path(".cache/weights"))
    ap.add_argument("--compare-int8", type=pathlib.Path,
                    help="the served int8 model, to compare with a re-quantized fp32 export")
    ap.add_argument("--report", type=pathlib.Path, default=pathlib.Path("results/fp32_export.json"))
    a = ap.parse_args()

    os.environ.setdefault("YOLO_OFFLINE", "1")  # no update checks or telemetry
    import onnx
    from ultralytics import YOLO

    weights = fetch_weights(a.cache)
    with tempfile.TemporaryDirectory() as tmp:
        local = pathlib.Path(tmp) / "best_deep.pt"
        shutil.copy(weights, local)  # Ultralytics writes the .onnx next to the .pt
        exported = YOLO(str(local)).export(format="onnx", imgsz=IMGSZ, opset=OPSET, simplify=True,
                                           dynamic=False, half=False, nms=False, device="cpu")
        model = onnx.load(exported)
        kept = [p for p in model.metadata_props if p.key != "date"]
        del model.metadata_props[:]
        model.metadata_props.extend(kept)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        onnx.save(model, str(a.out))

    got = sha256(a.out)
    print(f"{a.out}: {a.out.stat().st_size} bytes, SHA-256 {got}")
    if got != FP32_SHA256:
        print(f"expected SHA-256 {FP32_SHA256}: the export is not reproducible with these "
              "package versions", file=sys.stderr)
        return 1
    if a.compare_int8:
        compare_int8(a.out, a.compare_int8, a.report)
    return 0


def max_rel_diff(x, y):
    """Largest |x - y| / max(|y|, tiny) over the elements, or None if shapes differ."""
    import numpy as np

    if y is None or x.shape != y.shape:
        return None
    x64, y64 = x.astype(np.float64), y.astype(np.float64)
    return float(np.max(np.abs(x64 - y64) / np.maximum(np.abs(y64), 1e-30)))


def compare_int8(fp32: pathlib.Path, int8: pathlib.Path, report: pathlib.Path) -> None:
    """Quantize the fp32 export the way the served int8 file was made
    (quantize_dynamic, QUInt8) and compare the result with the served file."""
    import json

    import numpy as np
    import onnx
    import onnxruntime
    from onnx import numpy_helper
    from onnxruntime.quantization import QuantType, quantize_dynamic

    with tempfile.TemporaryDirectory() as tmp:
        ours_path = pathlib.Path(tmp) / "requantized.onnx"
        quantize_dynamic(str(fp32), str(ours_path), weight_type=QuantType.QUInt8)
        ours, served = onnx.load(str(ours_path)), onnx.load(str(int8))
        size_ours = ours_path.stat().st_size
    date = {p.key: p.value for p in served.metadata_props}.get("date", "")
    a = {i.name: numpy_helper.to_array(i) for i in ours.graph.initializer}
    b = {i.name: numpy_helper.to_array(i) for i in served.graph.initializer}
    same = sorted(k for k in a if k in b and a[k].dtype == b[k].dtype and a[k].shape == b[k].shape
                  and np.array_equal(a[k], b[k]))
    out = {
        "generated_by": "scripts/export_fp32.py --compare-int8",
        "weights": {"url": WEIGHTS_URL, "sha256": WEIGHTS_SHA256},
        "fp32": {"file": fp32.name, "bytes": fp32.stat().st_size, "sha256": FP32_SHA256,
                 "export": f"Ultralytics ONNX export, imgsz {IMGSZ}, opset {OPSET}, simplify, "
                           "static batch 1, no NMS, 'date' metadata removed"},
        "requantized": {"bytes": size_ours, "onnxruntime": onnxruntime.__version__,
                        "method": "quantize_dynamic, QuantType.QUInt8"},
        "served_int8": {"file": int8.name, "bytes": int8.stat().st_size, "sha256": sha256(int8),
                        "date_metadata_bytes": len(date)},
        "initializers": {"requantized": len(a), "served": len(b), "identical": len(same),
                         "different": {k: max_rel_diff(a[k], b.get(k)) for k in sorted(a)
                                       if k not in same}},
        "nodes": {"requantized": len(ours.graph.node), "served": len(served.graph.node)},
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(out, indent=1) + "\n")
    print(f"requantized: {len(same)} of {len(a)} initializers identical to the served int8 file; "
          f"wrote {report}")


if __name__ == "__main__":
    sys.exit(main())
