"""Service settings, read from PPE_* environment variables."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL_FILE = "ppe_yolov8s_320_int8dyn.onnx"


def effective_cpus(cgroup_root: Path = Path("/sys/fs/cgroup")) -> int:
    """CPUs this process may use: the cgroup CPU quota if set, else the affinity mask.

    ``os.cpu_count()`` reports the host's cores even under ``docker run --cpus=2`` or
    a Kubernetes CPU limit, so the quota is read from cgroup v2 (``cpu.max``) or
    cgroup v1 (``cpu.cfs_quota_us`` / ``cpu.cfs_period_us``).
    """
    available = len(os.sched_getaffinity(0))
    quota: float | None = None
    try:
        v2 = (cgroup_root / "cpu.max").read_text().split()
        if v2 and v2[0] != "max":
            quota = int(v2[0]) / int(v2[1])
    except (OSError, ValueError, IndexError):
        pass
    if quota is None:
        for base in (cgroup_root / "cpu", cgroup_root / "cpu,cpuacct", cgroup_root):
            try:
                q = int((base / "cpu.cfs_quota_us").read_text())
                p = int((base / "cpu.cfs_period_us").read_text())
            except (OSError, ValueError):
                continue
            if q > 0 and p > 0:
                quota = q / p
            break
    if quota is None:
        return max(1, available)
    return max(1, min(available, math.ceil(quota)))


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    value = float(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}], got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration. Every field maps to a PPE_* environment variable."""

    model_path: Path = Path("models") / DEFAULT_MODEL_FILE
    manifest_path: Path = Path("registry") / "manifest.json"
    #: Expected SHA-256 of the model; empty means "take it from the manifest".
    model_sha256: str = ""
    host: str = "0.0.0.0"  # noqa: S104 - a container must listen on all interfaces
    port: int = 8000
    #: Inference workers (threads, each running ONNX Runtime single-threaded).
    #: 0 means one per available CPU.
    workers: int = 0
    intra_op_threads: int = 1
    #: Requests admitted at once (queued plus running); more get 503.
    max_in_flight: int = 32
    request_timeout_s: float = 10.0
    max_upload_bytes: int = 8 * 1024 * 1024
    max_pixels: int = 25_000_000
    allowed_formats: frozenset[str] = field(
        default_factory=lambda: frozenset({"JPEG", "PNG", "WEBP"})
    )
    score_threshold: float = 0.25
    iou_threshold: float = 0.7
    input_size: int = 320
    log_level: str = "INFO"
    graceful_timeout_s: float = 25.0

    @property
    def resolved_workers(self) -> int:
        return self.workers if self.workers > 0 else effective_cpus()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        d = cls()
        formats = e.get("PPE_ALLOWED_FORMATS")
        return cls(
            model_path=Path(e.get("PPE_MODEL_PATH", str(d.model_path))),
            manifest_path=Path(e.get("PPE_MANIFEST_PATH", str(d.manifest_path))),
            model_sha256=e.get("PPE_MODEL_SHA256", "").strip().lower(),
            host=e.get("PPE_HOST", d.host),
            port=_int(e, "PPE_PORT", d.port, 1),
            workers=_int(e, "PPE_WORKERS", d.workers, 0),
            intra_op_threads=_int(e, "PPE_INTRA_OP_THREADS", d.intra_op_threads, 0),
            max_in_flight=_int(e, "PPE_MAX_IN_FLIGHT", d.max_in_flight, 1),
            request_timeout_s=_float(e, "PPE_REQUEST_TIMEOUT_S", d.request_timeout_s, 0.01, 600),
            max_upload_bytes=_int(e, "PPE_MAX_UPLOAD_BYTES", d.max_upload_bytes, 1),
            max_pixels=_int(e, "PPE_MAX_PIXELS", d.max_pixels, 1),
            allowed_formats=(
                frozenset(f.strip().upper() for f in formats.split(",") if f.strip())
                if formats
                else d.allowed_formats
            ),
            score_threshold=_float(e, "PPE_SCORE_THRESHOLD", d.score_threshold, 0.0, 1.0),
            iou_threshold=_float(e, "PPE_IOU_THRESHOLD", d.iou_threshold, 0.0, 1.0),
            input_size=_int(e, "PPE_INPUT_SIZE", d.input_size, 32),
            log_level=e.get("PPE_LOG_LEVEL", d.log_level).upper(),
            graceful_timeout_s=_float(e, "PPE_GRACEFUL_TIMEOUT_S", d.graceful_timeout_s, 0, 600),
        )
