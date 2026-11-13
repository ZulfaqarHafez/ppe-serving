"""HTTP API: validation, limits, timeouts, metrics, request ids and logs."""

from __future__ import annotations

import io
import json
import logging
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ppe_service.app import create_app
from ppe_service.config import Settings
from ppe_service.engine import DetectResult, ModelInfo, validate_image
from ppe_service.logs import JsonFormatter
from ppe_service.processing import Detection

from .conftest import sample_bytes

INFO = ModelInfo("fake", "0", "0" * 64, 320)


def _png(width: int = 64, height: int = 48, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 200, 30)).save(buf, format=fmt)
    return buf.getvalue()


class FakeDetector:
    """Validates like the real one, then returns one fixed detection."""

    def __init__(self, settings: Settings, delay: float = 0.0) -> None:
        self.settings = settings
        self.delay = delay
        self.release = threading.Event()
        self.release.set()

    def __call__(self, data: bytes, threshold: float) -> DetectResult:
        img = validate_image(data, self.settings.allowed_formats, self.settings.max_pixels)
        self.release.wait(5)
        time.sleep(self.delay)
        dets = [Detection(1, 0.9, 1, 2, 3, 4)] if threshold <= 0.9 else []
        return DetectResult(img.width, img.height, dets, {"inference": 1.0})


def _client(settings: Settings, fake: FakeDetector | None = None) -> TestClient:
    return TestClient(create_app(settings, fake or FakeDetector(settings), INFO, workers=1))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(Settings()) as c:
        yield c


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_detect_shape_and_request_id(client: TestClient) -> None:
    r = client.post(
        "/v1/detect",
        files={"file": ("a.png", _png(), "image/png")},
        headers={"X-Request-ID": "abc-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert r.headers["x-request-id"] == "abc-1"
    assert body["request_id"] == "abc-1"
    assert body["image"] == {"width": 64, "height": 48}
    assert body["model"]["sha256"] == "0" * 64
    assert body["detections"][0] == {
        "label": "Helmet",
        "class_id": 1,
        "score": 0.9,
        "missing_item": False,
        "box": {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0},
    }
    assert {"queue", "inference", "total"} <= set(body["timing_ms"])
    assert body["threshold"] == 0.25


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    r = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline"
    assert len(r.headers["x-request-id"]) == 32


def test_threshold_query(client: TestClient) -> None:
    files = {"file": ("a.png", _png(), "image/png")}
    assert client.post("/v1/detect?threshold=0.95", files=files).json()["detections"] == []
    assert client.post("/v1/detect?threshold=2", files=files).status_code == 422


@pytest.mark.parametrize(
    ("payload", "status", "reason"),
    [
        (b"", 400, "empty"),
        (b"hello, not an image", 415, "unsupported_format"),
        (_png(fmt="GIF"), 415, "unsupported_format"),
        (_png(fmt="BMP"), 415, "unsupported_format"),
        (_png()[:60], 400, "undecodable"),
    ],
)
def test_rejects_bad_uploads(client: TestClient, payload: bytes, status: int, reason: str) -> None:
    r = client.post("/v1/detect", files={"file": ("x", payload, "application/octet-stream")})
    assert r.status_code == status, r.text
    assert r.json()["error"] == reason


def test_missing_file_field(client: TestClient) -> None:
    assert client.post("/v1/detect", data={"x": "1"}).status_code == 422


def test_accepts_jpeg_and_webp(client: TestClient) -> None:
    for fmt in ("JPEG", "WEBP"):
        r = client.post("/v1/detect", files={"file": ("a", _png(fmt=fmt), "image/*")})
        assert r.status_code == 200, (fmt, r.text)


def test_too_many_pixels() -> None:
    with _client(Settings(max_pixels=1000)) as c:
        r = c.post("/v1/detect", files={"file": ("a.png", _png(100, 100), "image/png")})
        assert r.status_code == 413
        assert r.json()["error"] == "too_many_pixels"


def test_upload_too_large() -> None:
    with _client(Settings(max_upload_bytes=1000)) as c:
        big = b"\x89PNG" + b"0" * 200_000
        r = c.post("/v1/detect", files={"file": ("a.png", big, "image/png")})
        assert r.status_code == 413
        assert r.json()["error"] == "too_large"
        # Just over the file limit but under the early Content-Length check.
        r = c.post("/v1/detect", files={"file": ("a.png", b"0" * 1001, "image/png")})
        assert r.status_code == 413


def test_in_flight_cap_returns_503() -> None:
    settings = Settings(max_in_flight=1, request_timeout_s=5)
    fake = FakeDetector(settings)
    fake.release.clear()
    with _client(settings, fake) as c:
        results: list[int] = []
        first = threading.Thread(
            target=lambda: results.append(
                c.post("/v1/detect", files={"file": ("a.png", _png(), "image/png")}).status_code
            )
        )
        first.start()
        deadline = time.monotonic() + 5
        while c.app.state.pool.in_flight < 1 and time.monotonic() < deadline:  # type: ignore[attr-defined]
            time.sleep(0.01)
        r = c.post("/v1/detect", files={"file": ("a.png", _png(), "image/png")})
        assert r.status_code == 503
        assert r.json()["error"] == "overloaded"
        fake.release.set()
        first.join()
        assert results == [200]
        metrics = c.get("/metrics").text
        assert 'ppe_errors_total{reason="overloaded"} 1.0' in metrics


def test_timeout_returns_504() -> None:
    settings = Settings(request_timeout_s=0.05)
    with _client(settings, FakeDetector(settings, delay=0.3)) as c:
        r = c.post("/v1/detect", files={"file": ("a.png", _png(), "image/png")})
        assert r.status_code == 504
        assert r.json()["error"] == "timeout"


def test_metrics_exposed(client: TestClient) -> None:
    client.post("/v1/detect", files={"file": ("a.png", _png(), "image/png")})
    text = client.get("/metrics").text
    for name in (
        'ppe_http_requests_total{method="POST",route="/v1/detect",status="200"} 1.0',
        "ppe_http_request_duration_seconds_bucket",
        'ppe_stage_duration_seconds_count{stage="queue"} 1.0',
        'ppe_stage_duration_seconds_count{stage="inference"} 1.0',
        "ppe_in_flight_requests 0.0",
        "ppe_model_info{",
        "ppe_inference_workers 1.0",
        'ppe_detections_total{label="Helmet"} 1.0',
        "ppe_ready 1.0",
        "process_cpu_seconds_total",
    ):
        assert name in text, name
    client.get("/nope")
    assert 'route="other"' in client.get("/metrics").text


def test_not_ready_after_shutdown() -> None:
    settings = Settings()
    app = create_app(settings, FakeDetector(settings), INFO, workers=1)
    with TestClient(app):
        pass
    c = TestClient(app)
    assert c.get("/readyz").status_code == 503
    r = c.post("/v1/detect", files={"file": ("a.png", _png(), "image/png")})
    assert r.status_code == 503


def test_json_logs_carry_request_id(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ppe_service")
    client.post(
        "/v1/detect",
        files={"file": ("a.png", _png(), "image/png")},
        headers={"X-Request-ID": "r-42"},
    )
    records = [r for r in caplog.records if r.getMessage() == "request"]
    assert records
    line = json.loads(JsonFormatter().format(records[-1]))
    assert line["status"] == 200
    assert line["route"] == "/v1/detect"
    assert line["level"] == "info"
    assert "duration_ms" in line


def test_json_formatter_includes_context_request_id() -> None:
    from ppe_service.logs import request_id_var

    token = request_id_var.set("ctx-1")
    try:
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        rec.extra_field = 3
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello world"
    assert out["request_id"] == "ctx-1"
    assert out["extra_field"] == 3


def test_real_model_detects_on_a_sample(real_client: TestClient) -> None:
    r = real_client.post(
        "/v1/detect", files={"file": ("p.webp", sample_bytes("plant-cctv"), "image/webp")}
    )
    assert r.status_code == 200
    body = r.json()
    assert [d["label"] for d in body["detections"]] == ["No-vest", "No-Helmet"]
    assert all(d["missing_item"] for d in body["detections"])
    assert body["model"]["name"] == "ppe-yolov8s"
    assert body["timing_ms"]["inference"] > 0
