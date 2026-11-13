"""The Python reference pipeline the C++ code is compared with.

The same steps as the script that produced data/reference/samples.json:
Pillow decode, Pillow bilinear letterbox onto grey 114, onnxruntime, then the
site's decode and per-class NMS. Two deliberate differences from that script,
both to follow the site's ppeDetect.ts, which the C++ port follows too:
the resized side rounds halves up (Math.round), and boxes are clamped to the
image. Box arithmetic is done in float64, as JavaScript and the C++ port do.
"""
import math

import numpy as np
import onnxruntime as ort
from PIL import Image

NAMES = ["Gloves", "Helmet", "No-Helmet", "No-gloves", "No-vest", "Vest"]
PAD = 114


def session(model: str, threads: int) -> ort.InferenceSession:
    """threads 0 keeps the onnxruntime defaults; N > 0 sets intra-op N, inter-op 1
    (the same rule as the C++ Detector)."""
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if threads > 0:
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
    return ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])


def load_image(path: str) -> Image.Image:
    """Read and decode to RGB (convert() forces the decode)."""
    return Image.open(path).convert("RGB")


def letterbox(width: int, height: int, size: int):
    r = min(size / width, size / height)
    w = max(1, math.floor(width * r + 0.5))
    h = max(1, math.floor(height * r + 0.5))
    return r, (size - w) // 2, (size - h) // 2, w, h


def preprocess(img: Image.Image, size: int):
    r, px, py, w, h = letterbox(img.size[0], img.size[1], size)
    canvas = Image.new("RGB", (size, size), (PAD, PAD, PAD))
    canvas.paste(img.resize((w, h), Image.BILINEAR), (px, py))
    x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255
    return np.ascontiguousarray(x), (r, px, py, w, h)


def infer(sess: ort.InferenceSession, x: np.ndarray) -> np.ndarray:
    """The raw output0 block, [4 + classes, N]."""
    return sess.run(None, {sess.get_inputs()[0].name: x})[0][0]


def iou(a, b) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def postprocess(out: np.ndarray, box, threshold: float = 0.25, iou_limit: float = 0.7):
    """Detections as (class_id, score, [x1, y1, x2, y2]), highest score first."""
    r, px, py, w, h = box
    scores = out[4:].astype(np.float64)
    best, cls = scores.max(0), scores.argmax(0)
    max_x, max_y = w / r, h / r
    found = []
    for j in np.nonzero(best >= threshold)[0]:
        cx, cy, bw, bh = (float(v) for v in out[:4, j])
        found.append((int(cls[j]), float(best[j]), [
            min(max((cx - bw / 2 - px) / r, 0.0), max_x),
            min(max((cy - bh / 2 - py) / r, 0.0), max_y),
            min(max((cx + bw / 2 - px) / r, 0.0), max_x),
            min(max((cy + bh / 2 - py) / r, 0.0), max_y),
        ]))
    kept = []
    for d in sorted(found, key=lambda d: -d[1]):  # stable, like the C++ stable_sort
        if all(k[0] != d[0] or iou(k[2], d[2]) < iou_limit for k in kept):
            kept.append(d)
    return kept


def to_json(detections):
    return [{"label": NAMES[c], "class_id": c, "score": s, "box": b} for c, s, b in detections]
