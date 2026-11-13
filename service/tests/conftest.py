"""Shared fixtures. Tests that need the real model skip if it is absent, unless
PPE_REQUIRE_MODEL=1 (set in CI), in which case they fail."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ppe_service.app import create_app
from ppe_service.config import Settings
from ppe_service.engine import Detector, ModelInfo, load_session
from ppe_service.registry import ModelManifest, verify_file

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
MANIFEST = ROOT / "registry" / "manifest.json"


@pytest.fixture(scope="session")
def manifest() -> ModelManifest:
    return ModelManifest.load(MANIFEST)


@pytest.fixture(scope="session")
def model_path(manifest: ModelManifest) -> Path:
    path = Path(os.environ.get("PPE_MODEL_PATH", ROOT / "models" / manifest.filename))
    if not path.exists():
        if os.environ.get("PPE_REQUIRE_MODEL") == "1":
            pytest.fail(f"model missing at {path}; run scripts/fetch_model.py")
        pytest.skip("model not fetched; run scripts/fetch_model.py")
    verify_file(path, manifest.sha256)
    return path


@pytest.fixture(scope="session")
def detector(model_path: Path, manifest: ModelManifest) -> Detector:
    settings = Settings()
    det = Detector(
        load_session(model_path, 1),
        ModelInfo(manifest.name, manifest.version, manifest.sha256, settings.input_size),
        allowed_formats=settings.allowed_formats,
        max_pixels=settings.max_pixels,
        iou_threshold=settings.iou_threshold,
    )
    det.warm_up()
    return det


@pytest.fixture
def real_client(detector: Detector) -> Iterator[TestClient]:
    app = create_app(Settings(), detector.detect, detector.info, workers=2)
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def samples() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / "samples.json").read_text())
    return data


def sample_bytes(sample_id: str) -> bytes:
    return (DATA / "samples" / f"{sample_id}.webp").read_bytes()
