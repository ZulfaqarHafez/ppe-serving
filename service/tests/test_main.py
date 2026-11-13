"""The entry point refuses to start on a missing model or a checksum mismatch."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .conftest import ROOT


def _run(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **env_extra}
    return subprocess.run(
        [sys.executable, "-m", "ppe_service"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_exit_3_on_checksum_mismatch(tmp_path: Path) -> None:
    fake = tmp_path / "model.onnx"
    fake.write_bytes(b"tampered")
    proc = _run({"PPE_MODEL_PATH": str(fake)})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "checksum mismatch" in proc.stdout


def test_exit_3_on_pinned_hash_override(model_path: Path) -> None:
    proc = _run({"PPE_MODEL_PATH": str(model_path), "PPE_MODEL_SHA256": "0" * 64})
    assert proc.returncode == 3


def test_exit_2_on_missing_model(tmp_path: Path) -> None:
    proc = _run({"PPE_MODEL_PATH": str(tmp_path / "absent.onnx")})
    assert proc.returncode == 2
    assert "missing" in proc.stdout


def test_exit_4_on_bad_config() -> None:
    proc = _run({"PPE_MAX_IN_FLIGHT": "0"})
    assert proc.returncode == 4
