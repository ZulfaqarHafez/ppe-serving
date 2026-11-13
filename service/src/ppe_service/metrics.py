"""Prometheus metrics. Each app instance owns its registry, so tests stay isolated."""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)

LATENCY_BUCKETS = (
    0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0
)  # fmt: skip
STAGE_BUCKETS = (
    0.0005, 0.001, 0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.1, 0.2, 0.5, 1.0, 2.5
)  # fmt: skip


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        ProcessCollector(registry=r)
        PlatformCollector(registry=r)
        self.requests = Counter(
            "ppe_http_requests_total",
            "HTTP requests by route, method and status code",
            ["route", "method", "status"],
            registry=r,
        )
        self.latency = Histogram(
            "ppe_http_request_duration_seconds",
            "Server-side HTTP request latency",
            ["route"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self.stage = Histogram(
            "ppe_stage_duration_seconds",
            "Time per pipeline stage of /v1/detect (queue, decode, preprocess, inference, "
            "postprocess)",
            ["stage"],
            buckets=STAGE_BUCKETS,
            registry=r,
        )
        self.in_flight = Gauge(
            "ppe_in_flight_requests", "Detect requests admitted and not yet finished", registry=r
        )
        self.in_flight_limit = Gauge(
            "ppe_in_flight_limit", "Admission cap; requests above it get 503", registry=r
        )
        self.errors = Counter(
            "ppe_errors_total", "Detect requests that did not succeed, by reason", ["reason"],
            registry=r,
        )  # fmt: skip
        self.detections = Counter(
            "ppe_detections_total", "Detections returned, by class", ["label"], registry=r
        )
        self.model_info = Gauge(
            "ppe_model_info",
            "Loaded model (value is always 1)",
            ["name", "version", "sha256", "input_size"],
            registry=r,
        )
        self.workers = Gauge("ppe_inference_workers", "Inference worker threads", registry=r)
        self.intra_op_threads = Gauge(
            "ppe_intra_op_threads", "ONNX Runtime threads per inference call", registry=r
        )
        self.ready = Gauge("ppe_ready", "1 when the service accepts detect requests", registry=r)

    def render(self) -> bytes:
        return generate_latest(self.registry)
