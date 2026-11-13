"""Parity: the service reproduces every detection the site recorded in samples.json.

samples.json was made on the site with Pillow (bilinear resize) and onnxruntime
in Python. For each of the five sample images and both thresholds the site
reports (0.25 and 0.5), the service must return the same labels in the same
order, and every score within SCORE_TOLERANCE of the recorded one. samples.json
rounds scores to 3 decimals, so 0.0005 of the tolerance is that rounding alone.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sample_bytes

SCORE_TOLERANCE = 0.001
THRESHOLDS = ("0.25", "0.5")


def _cases() -> list[tuple[str, str]]:
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "data" / "samples.json").read_text())
    return [(s["id"], t) for s in data["samples"] for t in THRESHOLDS]


@pytest.mark.parametrize(("sample_id", "threshold"), _cases())
def test_service_matches_samples_json(
    real_client: TestClient, samples: dict[str, Any], sample_id: str, threshold: str
) -> None:
    sample = next(s for s in samples["samples"] if s["id"] == sample_id)
    expected = sample["at"][threshold]["detections"]
    r = real_client.post(
        f"/v1/detect?threshold={threshold}",
        files={"file": (f"{sample_id}.webp", sample_bytes(sample_id), "image/webp")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image"] == {"width": sample["width"], "height": sample["height"]}
    got = body["detections"]
    assert [d["label"] for d in got] == [e["label"] for e in expected]
    for g, e in zip(got, expected, strict=True):
        assert abs(g["score"] - e["score"]) <= SCORE_TOLERANCE, (g, e)
