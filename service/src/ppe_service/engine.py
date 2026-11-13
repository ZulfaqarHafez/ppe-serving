"""Image validation, the inference pipeline and the worker pool."""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, UnidentifiedImageError

from .processing import Detection, decode_candidates, preprocess, select_detections

log = logging.getLogger(__name__)

# The service checks the pixel count itself before decoding (see validate_image),
# with its own configurable limit, so Pillow's global bomb guard is not needed.
Image.MAX_IMAGE_PIXELS = None


class ImageRejectedError(Exception):
    """The upload is not an image the service accepts. Carries the HTTP status."""

    def __init__(self, status: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: str
    version: str
    sha256: str
    input_size: int


@dataclass(slots=True)
class DetectResult:
    width: int
    height: int
    detections: list[Detection]
    timings_ms: dict[str, float] = field(default_factory=dict)


def validate_image(data: bytes, allowed_formats: frozenset[str], max_pixels: int) -> Image.Image:
    """Open and fully decode an upload, or raise ImageRejectedError.

    The format and the pixel count are checked from the header, before the
    pixels are decoded, so an oversized image is refused cheaply.
    """
    if not data:
        raise ImageRejectedError(400, "empty", "the uploaded file is empty")
    try:
        image = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as exc:
        raise ImageRejectedError(415, "unsupported_format", "not a recognised image") from exc
    except (OSError, ValueError) as exc:
        raise ImageRejectedError(400, "undecodable", f"cannot read image: {exc}") from exc
    fmt = (image.format or "").upper()
    if fmt not in allowed_formats:
        raise ImageRejectedError(
            415, "unsupported_format", f"format {fmt or 'unknown'} not in {sorted(allowed_formats)}"
        )
    width, height = image.size
    if width < 1 or height < 1:
        raise ImageRejectedError(400, "undecodable", "image has no pixels")
    if width * height > max_pixels:
        raise ImageRejectedError(
            413, "too_many_pixels", f"{width}x{height} exceeds the {max_pixels} pixel limit"
        )
    try:
        image.load()
        return image.convert("RGB")
    except (OSError, ValueError, SyntaxError) as exc:
        raise ImageRejectedError(400, "undecodable", f"cannot decode image: {exc}") from exc


class Session(Protocol):
    def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[Any]: ...


def load_session(model_path: Path, intra_op_threads: int) -> Any:
    """An ONNX Runtime CPU session. Run() is thread-safe, so the workers share it."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_op_threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])


class Detector:
    """The full pipeline for one image: validate, letterbox, run, decode, NMS."""

    def __init__(
        self,
        session: Session,
        info: ModelInfo,
        *,
        allowed_formats: frozenset[str],
        max_pixels: int,
        iou_threshold: float,
        input_name: str = "images",
    ) -> None:
        self.session = session
        self.info = info
        self.allowed_formats = allowed_formats
        self.max_pixels = max_pixels
        self.iou_threshold = iou_threshold
        self.input_name = input_name

    def warm_up(self) -> None:
        size = self.info.input_size
        self.session.run(None, {self.input_name: np.zeros((1, 3, size, size), np.float32)})

    def detect(self, data: bytes, threshold: float) -> DetectResult:
        t0 = time.perf_counter()
        image = validate_image(data, self.allowed_formats, self.max_pixels)
        t1 = time.perf_counter()
        tensor, box = preprocess(image, self.info.input_size)
        t2 = time.perf_counter()
        output = self.session.run(None, {self.input_name: tensor})[0]
        t3 = time.perf_counter()
        found = decode_candidates(np.asarray(output, dtype=np.float32), box, threshold)
        kept = select_detections(found, threshold, self.iou_threshold)
        t4 = time.perf_counter()
        return DetectResult(
            width=image.width,
            height=image.height,
            detections=kept,
            timings_ms={
                "decode": (t1 - t0) * 1000,
                "preprocess": (t2 - t1) * 1000,
                "inference": (t3 - t2) * 1000,
                "postprocess": (t4 - t3) * 1000,
            },
        )


class DetectFn(Protocol):
    def __call__(self, data: bytes, threshold: float) -> DetectResult: ...


class WorkerPool:
    """A fixed pool of inference threads with an admission cap.

    ``try_admit`` counts a request in; the slot is released when its work has
    really finished (or was cancelled before starting), not when the HTTP
    response was sent, so a timed-out request still holds its slot while a
    worker is busy with it.
    """

    def __init__(self, workers: int, max_in_flight: int) -> None:
        self.workers = workers
        self.max_in_flight = max_in_flight
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="infer")
        self._lock = threading.Lock()
        self._in_flight = 0
        self.on_change: Callable[[int], None] = lambda _n: None

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def try_admit(self) -> bool:
        with self._lock:
            if self._in_flight >= self.max_in_flight:
                return False
            self._in_flight += 1
            n = self._in_flight
        self.on_change(n)
        return True

    def release(self) -> None:
        with self._lock:
            self._in_flight -= 1
            n = self._in_flight
        self.on_change(n)

    def submit(self, fn: DetectFn, data: bytes, threshold: float) -> Future[DetectResult]:
        """Run ``fn`` on a worker; the result's timings gain a ``queue`` entry."""
        queued_at = time.perf_counter()

        def job() -> DetectResult:
            started = time.perf_counter()
            result = fn(data, threshold)
            result.timings_ms["queue"] = (started - queued_at) * 1000
            return result

        future = self._executor.submit(job)
        future.add_done_callback(lambda _f: self.release())
        return future

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
