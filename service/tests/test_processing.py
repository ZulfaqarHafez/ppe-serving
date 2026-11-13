"""Unit tests for pre- and post-processing (no model needed)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from ppe_service.processing import (
    CLASS_NAMES,
    PAD_VALUE,
    Detection,
    compute_letterbox,
    decode_candidates,
    iou,
    is_missing_item,
    preprocess,
    select_detections,
)


def test_letterbox_landscape_matches_site_arithmetic() -> None:
    # site-backs.webp is 640 x 486: ratio 0.5, 320 x 243, centred vertically.
    box = compute_letterbox(640, 486, 320)
    assert box.ratio == 0.5
    assert (box.width, box.height) == (320, 243)
    assert (box.pad_x, box.pad_y) == (0, 38)


def test_letterbox_rounds_halves_up_like_math_round() -> None:
    # 10 x 5 into 5: ratio 0.5, height 2.5 rounds to 3 as Math.round does
    # (Python's round() would give 2), and the padding is floor((5 - 3) / 2) = 1.
    box = compute_letterbox(10, 5, 5)
    assert (box.width, box.height, box.pad_x, box.pad_y) == (5, 3, 0, 1)
    # 10 x 3 into 4: ratio 0.4, height 1.2 -> 1, padding floor(1.5) = 1.
    box = compute_letterbox(10, 3, 4)
    assert (box.width, box.height, box.pad_y) == (4, 1, 1)


def test_letterbox_portrait_and_square() -> None:
    box = compute_letterbox(640, 640, 320)
    assert (box.ratio, box.width, box.height, box.pad_x, box.pad_y) == (0.5, 320, 320, 0, 0)
    box = compute_letterbox(300, 600, 320)
    assert (box.width, box.height, box.pad_x, box.pad_y) == (160, 320, 80, 0)


def test_letterbox_rejects_empty() -> None:
    with pytest.raises(ValueError, match="positive"):
        compute_letterbox(0, 10, 320)


def test_preprocess_shape_padding_and_scale() -> None:
    img = Image.new("RGB", (640, 320), (255, 0, 0))
    tensor, box = preprocess(img, 320)
    assert tensor.shape == (1, 3, 320, 320)
    assert tensor.dtype == np.float32
    assert (box.pad_y, box.height) == (80, 160)
    pad = np.float32(PAD_VALUE) / np.float32(255)
    assert tensor[0, :, 0, 0].tolist() == [pad, pad, pad]
    assert tensor[0, :, 160, 160].tolist() == [1.0, 0.0, 0.0]
    assert tensor[0, :, 319, 319].tolist() == [pad, pad, pad]


def test_preprocess_converts_non_rgb_modes() -> None:
    tensor, _ = preprocess(Image.new("L", (32, 32), 255), 32)
    assert float(tensor.min()) == 1.0
    tensor, _ = preprocess(Image.new("RGBA", (32, 32), (0, 0, 255, 0)), 32)
    assert tensor[0, 2].min() == 1.0


def _output(columns: list[tuple[float, float, float, float, list[float]]]) -> np.ndarray:
    out = np.zeros((1, 4 + len(CLASS_NAMES), len(columns)), dtype=np.float32)
    for j, (cx, cy, w, h, scores) in enumerate(columns):
        out[0, :4, j] = (cx, cy, w, h)
        out[0, 4:, j] = scores
    return out


def test_decode_maps_back_to_image_pixels_and_clamps() -> None:
    box = compute_letterbox(640, 480, 320)  # ratio 0.5, pad_y 40
    out = _output(
        [
            (160, 160, 40, 20, [0, 0.9, 0, 0, 0, 0]),
            (5, 45, 20, 20, [0, 0, 0, 0, 0.6, 0]),  # crosses the left and top edges
            (100, 100, 10, 10, [0.1, 0, 0, 0, 0, 0]),  # below the floor
        ]
    )
    found = decode_candidates(out, box, 0.25)
    assert [d.label for d in found] == ["Helmet", "No-vest"]
    helmet, novest = found
    assert helmet.score == pytest.approx(0.9, abs=1e-6)
    assert (helmet.x1, helmet.y1, helmet.x2, helmet.y2) == (280.0, 220.0, 360.0, 260.0)
    assert (novest.x1, novest.y1) == (0.0, 0.0)
    assert novest.x2 == pytest.approx(30.0)


def test_decode_ties_keep_first_class_and_floor_is_inclusive() -> None:
    box = compute_letterbox(320, 320, 320)
    out = _output([(10, 10, 4, 4, [0.5, 0.5, 0, 0, 0, 0])])
    (d,) = decode_candidates(out, box, 0.5)
    assert d.class_id == 0


def test_decode_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="shape"):
        decode_candidates(np.zeros((1, 9, 5), np.float32), compute_letterbox(1, 1, 1), 0.1)


def _det(cls: int, score: float, x1: float, y1: float, x2: float, y2: float) -> Detection:
    return Detection(cls, score, x1, y1, x2, y2)


def test_iou() -> None:
    a = _det(0, 1, 0, 0, 10, 10)
    assert iou(a, a) == 1.0
    assert iou(a, _det(0, 1, 5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert iou(a, _det(0, 1, 20, 20, 30, 30)) == 0.0
    assert iou(_det(0, 1, 0, 0, 0, 0), _det(0, 1, 0, 0, 0, 0)) == 0.0


def test_nms_is_per_class_sorted_and_thresholded() -> None:
    found = [
        _det(1, 0.6, 0, 0, 10, 10),
        _det(1, 0.9, 0, 0, 10, 9),  # overlaps the first, higher score: keeps this one
        _det(5, 0.7, 0, 0, 10, 10),  # same box, other class: kept
        _det(1, 0.8, 50, 50, 60, 60),  # same class, no overlap: kept
        _det(2, 0.2, 0, 0, 1, 1),  # under threshold
    ]
    kept = select_detections(found, 0.25)
    assert [(d.class_id, d.score) for d in kept] == [(1, 0.9), (1, 0.8), (5, 0.7)]


def test_nms_iou_limit_is_exclusive() -> None:
    a = _det(0, 0.9, 0, 0, 10, 10)
    b = _det(0, 0.8, 0, 0, 10, 7)  # IoU exactly 0.7
    assert len(select_detections([a, b], 0.0, 0.7)) == 1
    assert len(select_detections([a, b], 0.0, 0.71)) == 2


def test_nms_stable_for_equal_scores() -> None:
    a = _det(0, 0.5, 0, 0, 10, 10)
    b = _det(3, 0.5, 0, 0, 10, 10)
    assert select_detections([b, a], 0.0) == [b, a]


def test_missing_item() -> None:
    assert is_missing_item("No-vest")
    assert not is_missing_item("Vest")
