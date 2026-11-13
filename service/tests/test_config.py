"""Settings from PPE_* variables and CPU detection from cgroups."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppe_service.config import Settings, effective_cpus


def test_defaults() -> None:
    s = Settings.from_env({})
    assert s.workers == 0
    assert s.intra_op_threads == 1
    assert s.score_threshold == 0.25
    assert s.iou_threshold == 0.7
    assert s.allowed_formats == frozenset({"JPEG", "PNG", "WEBP"})
    assert s.resolved_workers >= 1


def test_env_overrides() -> None:
    s = Settings.from_env(
        {
            "PPE_WORKERS": "3",
            "PPE_INTRA_OP_THREADS": "2",
            "PPE_MAX_IN_FLIGHT": "5",
            "PPE_REQUEST_TIMEOUT_S": "1.5",
            "PPE_ALLOWED_FORMATS": "png, jpeg",
            "PPE_MODEL_SHA256": " ABC ",
            "PPE_LOG_LEVEL": "debug",
            "PPE_MODEL_PATH": "/models/m.onnx",
        }
    )
    assert (s.workers, s.resolved_workers, s.intra_op_threads, s.max_in_flight) == (3, 3, 2, 5)
    assert s.request_timeout_s == 1.5
    assert s.allowed_formats == frozenset({"PNG", "JPEG"})
    assert s.model_sha256 == "abc"
    assert s.log_level == "DEBUG"
    assert s.model_path == Path("/models/m.onnx")


@pytest.mark.parametrize(
    ("name", "value"),
    [("PPE_MAX_IN_FLIGHT", "0"), ("PPE_SCORE_THRESHOLD", "1.5"), ("PPE_PORT", "x")],
)
def test_bad_values_raise(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        Settings.from_env({name: value})


def test_effective_cpus_cgroup_v2(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("150000 100000\n")
    assert effective_cpus(tmp_path) == min(2, effective_cpus(tmp_path / "none"))


def test_effective_cpus_cgroup_v2_unlimited(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert effective_cpus(tmp_path) == effective_cpus(tmp_path / "none")


def test_effective_cpus_cgroup_v1(tmp_path: Path) -> None:
    cpu = tmp_path / "cpu"
    cpu.mkdir()
    (cpu / "cpu.cfs_quota_us").write_text("100000\n")
    (cpu / "cpu.cfs_period_us").write_text("100000\n")
    assert effective_cpus(tmp_path) == 1


def test_effective_cpus_cgroup_v1_unlimited(tmp_path: Path) -> None:
    cpu = tmp_path / "cpu"
    cpu.mkdir()
    (cpu / "cpu.cfs_quota_us").write_text("-1\n")
    (cpu / "cpu.cfs_period_us").write_text("100000\n")
    assert effective_cpus(tmp_path) == effective_cpus(tmp_path / "none")
