"""Parity report: the service's answers on the five site samples against samples.json.

Runs every sample at thresholds 0.25 and 0.5 through the HTTP API (in process,
with the real model) and records labels, scores and the largest score gap.
Writes results/parity.json. The same check is a test: tests/test_parity.py.
Usage: uv run python scripts/parity_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import onnxruntime as ort
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ppe_service.app import create_app  # noqa: E402
from ppe_service.config import Settings  # noqa: E402
from ppe_service.engine import Detector, ModelInfo, load_session  # noqa: E402
from ppe_service.registry import ModelManifest, verify_file  # noqa: E402

TOLERANCE = 0.001


def main() -> int:
    manifest = ModelManifest.load(ROOT / "registry" / "manifest.json")
    model = ROOT / "models" / manifest.filename
    sha = verify_file(model, manifest.sha256)
    settings = Settings()
    det = Detector(
        load_session(model, 1),
        ModelInfo(manifest.name, manifest.version, sha, settings.input_size),
        allowed_formats=settings.allowed_formats,
        max_pixels=settings.max_pixels,
        iou_threshold=settings.iou_threshold,
    )
    data = ROOT / "tests" / "data"
    reference = json.loads((data / "samples.json").read_text())
    cases = []
    worst = 0.0
    all_match = True
    with TestClient(create_app(settings, det.detect, det.info, workers=1)) as client:
        for s in reference["samples"]:
            for thr in ("0.25", "0.5"):
                body = client.post(
                    f"/v1/detect?threshold={thr}",
                    files={"file": ("x.webp", (data / "samples" / f"{s['id']}.webp").read_bytes())},
                ).json()
                got = [(d["label"], d["score"]) for d in body["detections"]]
                exp = [(d["label"], d["score"]) for d in s["at"][thr]["detections"]]
                labels_match = [g[0] for g in got] == [e[0] for e in exp]
                gaps = [abs(g[1] - e[1]) for g, e in zip(got, exp, strict=False)]
                gap = max(gaps, default=0.0)
                worst = max(worst, gap)
                ok = labels_match and gap <= TOLERANCE
                all_match &= ok
                cases.append(
                    {
                        "sample": s["id"],
                        "threshold": float(thr),
                        "expected": [{"label": lb, "score": sc} for lb, sc in exp],
                        "service": [{"label": lb, "score": round(sc, 6)} for lb, sc in got],
                        "labels_match": labels_match,
                        "max_score_gap": round(gap, 6),
                        "pass": ok,
                    }
                )
    report = {
        "reference": "tests/data/samples.json (the site's record, Pillow bilinear + onnxruntime)",
        "model_sha256": sha,
        "onnxruntime": ort.__version__,
        "score_tolerance": TOLERANCE,
        "tolerance_note": "samples.json rounds scores to 3 decimals, so 0.0005 is rounding alone",
        "cases": len(cases),
        "detections_compared": sum(len(c["expected"]) for c in cases),
        "all_pass": all_match,
        "worst_score_gap": round(worst, 6),
        "results": cases,
    }
    out = ROOT / "results" / "parity.json"
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=1))
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
