"""Pre- and post-processing for the PPE detector, ported from the site.

A Python port of ``src/components/demos/ppeDetect.ts`` on zulfaqarhafez.com and
of the script that produced the reference results in ``samples.json`` (Pillow
bilinear resize, onnxruntime). ``ros2/src/ppe_detector`` in this repository holds
a C++ port of the same algorithm.

Input ``images``: float32 [1, 3, S, S], RGB, letterboxed to a square with grey
114 padding, scaled 0 to 1. Output ``output0``: float32 [1, 10, N]; column j is
one candidate: rows 0 to 3 are centre x, centre y, width, height in letterboxed
pixels, rows 4 to 9 are class scores (already 0 to 1). There is no objectness
score and no NMS in the graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from PIL import Image

#: Class order of the exported model (ppeDetect.ts PPE_CLASSES).
CLASS_NAMES: tuple[str, ...] = ("Gloves", "Helmet", "No-Helmet", "No-gloves", "No-vest", "Vest")
PAD_VALUE = 114
#: Ultralytics default IoU for NMS, as used by the site.
DEFAULT_IOU = 0.7

FloatArray = npt.NDArray[np.float32]


def is_missing_item(label: str) -> bool:
    """True for the "No-..." classes, which mean an item is missing."""
    return label.startswith("No-")


@dataclass(frozen=True, slots=True)
class Letterbox:
    """Where the image goes inside the square model input."""

    size: int
    ratio: float
    pad_x: int
    pad_y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Detection:
    """One detection; box corners in original image pixels."""

    class_id: int
    score: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def label(self) -> str:
        return CLASS_NAMES[self.class_id]


def _js_round(value: float) -> int:
    """JavaScript Math.round: halves round up (towards +infinity)."""
    return math.floor(value + 0.5)


def compute_letterbox(width: int, height: int, size: int) -> Letterbox:
    """Same arithmetic as letterbox() in ppeDetect.ts (Math.round, Math.floor)."""
    if width <= 0 or height <= 0 or size <= 0:
        raise ValueError("width, height and size must be positive")
    ratio = min(size / width, size / height)
    w = _js_round(width * ratio)
    h = _js_round(height * ratio)
    return Letterbox(
        size=size,
        ratio=ratio,
        pad_x=math.floor((size - w) / 2),
        pad_y=math.floor((size - h) / 2),
        width=w,
        height=h,
    )


def preprocess(image: Image.Image, size: int) -> tuple[FloatArray, Letterbox]:
    """Letterbox an image into the [1, 3, size, size] float tensor the model expects.

    The resize is Pillow's ``Image.resize(..., BILINEAR)``, which is what made the
    reference results; it averages over the source footprint when shrinking.
    """
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    box = compute_letterbox(rgb.width, rgb.height, size)
    resized = rgb.resize((box.width, box.height), Image.Resampling.BILINEAR)
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[box.pad_y : box.pad_y + box.height, box.pad_x : box.pad_x + box.width] = np.asarray(
        resized, dtype=np.uint8
    )
    tensor = canvas.astype(np.float32) / np.float32(255.0)
    chw = np.ascontiguousarray(tensor.transpose(2, 0, 1))[np.newaxis, ...]
    return chw, box


def decode_candidates(output: FloatArray, box: Letterbox, floor: float) -> list[Detection]:
    """Every candidate whose best class score clears ``floor``, in image pixels.

    ``output`` is output0 with shape [1, 4 + classes, N] or [4 + classes, N]
    (candidates() in ppeDetect.ts). Ties between classes keep the first class,
    as the site's strict ``>`` comparison does.
    """
    block = output[0] if output.ndim == 3 else output
    if block.ndim != 2 or block.shape[0] != 4 + len(CLASS_NAMES):
        raise ValueError(f"unexpected output shape {output.shape}")
    data = block.astype(np.float64)
    scores = data[4:]
    cls = np.argmax(scores, axis=0)
    best = scores[cls, np.arange(scores.shape[1])]
    keep = np.nonzero(best >= floor)[0]
    if keep.size == 0:
        return []
    cx, cy, w, h = (data[i, keep] for i in range(4))
    max_x = box.width / box.ratio
    max_y = box.height / box.ratio
    x1 = np.clip((cx - w / 2 - box.pad_x) / box.ratio, 0.0, max_x)
    y1 = np.clip((cy - h / 2 - box.pad_y) / box.ratio, 0.0, max_y)
    x2 = np.clip((cx + w / 2 - box.pad_x) / box.ratio, 0.0, max_x)
    y2 = np.clip((cy + h / 2 - box.pad_y) / box.ratio, 0.0, max_y)
    return [
        Detection(
            class_id=int(cls[j]),
            score=float(best[j]),
            x1=float(x1[i]),
            y1=float(y1[i]),
            x2=float(x2[i]),
            y2=float(y2[i]),
        )
        for i, j in enumerate(keep)
    ]


def iou(a: Detection, b: Detection) -> float:
    """Intersection over union of two boxes."""
    w = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    h = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = w * h
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


def select_detections(
    found: list[Detection], threshold: float, iou_limit: float = DEFAULT_IOU
) -> list[Detection]:
    """Threshold, then per-class NMS, highest score first (selectDetections()).

    ``sorted`` is stable, as Array.prototype.sort is, so ties keep candidate order.
    """
    ranked = sorted((d for d in found if d.score >= threshold), key=lambda d: -d.score)
    kept: list[Detection] = []
    for d in ranked:
        if all(k.class_id != d.class_id or iou(k, d) < iou_limit for k in kept):
            kept.append(d)
    return kept
