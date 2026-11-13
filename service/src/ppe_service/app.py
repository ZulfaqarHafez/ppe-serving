"""The FastAPI application: /v1/detect, /healthz, /readyz, /metrics."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .engine import DetectFn, DetectResult, ImageRejectedError, ModelInfo, WorkerPool
from .logs import request_id_var
from .metrics import Metrics

log = logging.getLogger("ppe_service")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_KNOWN_ROUTES = {"/v1/detect", "/healthz", "/readyz", "/metrics"}
_QUIET_ROUTES = {"/healthz", "/readyz", "/metrics"}
# Multipart framing around the file; generous so a file just under the limit passes.
_MULTIPART_OVERHEAD = 64 * 1024


class Box(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class DetectionOut(BaseModel):
    label: str
    class_id: int
    score: float
    missing_item: bool
    box: Box


class ModelOut(BaseModel):
    name: str
    version: str
    sha256: str
    input_size: int


class DetectResponse(BaseModel):
    request_id: str
    model: ModelOut
    image: dict[str, int]
    threshold: float
    iou_threshold: float
    detections: list[DetectionOut]
    timing_ms: dict[str, float]


class ServiceState:
    def __init__(self) -> None:
        self.ready = False
        self.draining = False


def _error(status: int, reason: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"error": reason, "detail": detail, "request_id": request_id_var.get()},
        status_code=status,
    )


class RequestContextMiddleware:
    """Request id, access log, request metrics and the early upload-size check.

    A plain ASGI middleware (not BaseHTTPMiddleware) so the request id context
    variable is visible in the endpoint and its logs.
    """

    def __init__(self, app: ASGIApp, metrics: Metrics, max_body: int) -> None:
        self.app = app
        self.metrics = metrics
        self.max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        supplied = headers.get("x-request-id", "")
        rid = supplied if _SAFE_ID.match(supplied) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        path: str = scope["path"]
        try:
            length = headers.get("content-length", "")
            if path == "/v1/detect" and length.isdigit() and int(length) > self.max_body:
                self.metrics.errors.labels("too_large").inc()
                response = _error(413, "too_large", f"upload exceeds {self.max_body} bytes")
                await response(scope, receive, send_wrapper)
            else:
                await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route_obj = scope.get("route")
            route = getattr(route_obj, "path", None) or (path if path in _KNOWN_ROUTES else "other")
            method = scope.get("method", "")
            self.metrics.requests.labels(route, method, str(status)).inc()
            self.metrics.latency.labels(route).observe(elapsed)
            level = logging.DEBUG if route in _QUIET_ROUTES and status < 400 else logging.INFO
            log.log(
                level,
                "request",
                extra={
                    "method": method,
                    "path": path,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
            request_id_var.reset(token)


def create_app(
    settings: Settings,
    detect_fn: DetectFn,
    model: ModelInfo,
    *,
    workers: int | None = None,
    on_shutdown: list[Any] | None = None,
) -> FastAPI:
    """Build the app around an already loaded, already verified detector."""
    metrics = Metrics()
    state = ServiceState()
    n_workers = workers if workers is not None else settings.resolved_workers
    pool = WorkerPool(n_workers, settings.max_in_flight)
    pool.on_change = metrics.in_flight.set
    metrics.in_flight_limit.set(settings.max_in_flight)
    metrics.workers.set(n_workers)
    metrics.intra_op_threads.set(settings.intra_op_threads)
    metrics.model_info.labels(model.name, model.version, model.sha256, str(model.input_size)).set(1)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        state.ready = True
        metrics.ready.set(1)
        log.info(
            "ready",
            extra={
                "model": model.name,
                "version": model.version,
                "sha256": model.sha256,
                "workers": n_workers,
                "intra_op_threads": settings.intra_op_threads,
                "max_in_flight": settings.max_in_flight,
            },
        )
        try:
            yield
        finally:
            # Uvicorn has stopped accepting connections and waited for open
            # requests by now; finish anything still on a worker, then exit.
            state.ready = False
            state.draining = True
            metrics.ready.set(0)
            log.info("draining", extra={"in_flight": pool.in_flight})
            await asyncio.to_thread(pool.shutdown)
            for hook in on_shutdown or []:
                hook()
            log.info("stopped", extra={"in_flight": pool.in_flight})

    app = FastAPI(
        title="PPE detection service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.metrics = metrics
    app.state.pool = pool
    app.state.service = state
    app.add_middleware(
        RequestContextMiddleware,
        metrics=metrics,
        max_body=settings.max_upload_bytes + _MULTIPART_OVERHEAD,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up and the event loop answers."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness: the model is loaded and the service is not draining."""
        if state.ready and not state.draining:
            return JSONResponse({"status": "ready", "in_flight": pool.in_flight})
        return JSONResponse({"status": "not_ready"}, status_code=503)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        return Response(metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.post(
        "/v1/detect",
        response_model=DetectResponse,
        responses={
            400: {"description": "Empty or undecodable image"},
            413: {"description": "Upload or pixel count over the limit"},
            415: {"description": "Not a JPEG, PNG or WebP image"},
            503: {"description": "In-flight cap reached or draining"},
            504: {"description": "Request timeout"},
        },
    )
    async def detect(
        request: Request,
        file: Annotated[UploadFile, File(description="JPEG, PNG or WebP image")],
        threshold: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    ) -> Any:
        received = time.perf_counter()
        thr = settings.score_threshold if threshold is None else threshold
        if not state.ready or state.draining:
            metrics.errors.labels("not_ready").inc()
            return _error(503, "not_ready", "service is starting or shutting down")
        data = await file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            metrics.errors.labels("too_large").inc()
            return _error(413, "too_large", f"upload exceeds {settings.max_upload_bytes} bytes")
        if not pool.try_admit():
            metrics.errors.labels("overloaded").inc()
            return _error(503, "overloaded", f"{settings.max_in_flight} requests already in flight")
        try:
            future = pool.submit(detect_fn, data, thr)
        except BaseException:
            pool.release()
            raise
        try:
            result: DetectResult = await asyncio.wait_for(
                asyncio.wrap_future(future), timeout=settings.request_timeout_s
            )
        except TimeoutError:
            metrics.errors.labels("timeout").inc()
            log.warning("timeout", extra={"timeout_s": settings.request_timeout_s})
            return _error(504, "timeout", f"no result within {settings.request_timeout_s} s")
        except ImageRejectedError as exc:
            metrics.errors.labels(exc.reason).inc()
            return _error(exc.status, exc.reason, exc.detail)
        except Exception:
            metrics.errors.labels("internal").inc()
            log.exception("inference failed")
            return _error(500, "internal", "inference failed")
        for stage, ms in result.timings_ms.items():
            metrics.stage.labels(stage).observe(ms / 1000)
        for d in result.detections:
            metrics.detections.labels(d.label).inc()
        timing = {k: round(v, 3) for k, v in result.timings_ms.items()}
        timing["total"] = round((time.perf_counter() - received) * 1000, 3)
        return DetectResponse(
            request_id=request_id_var.get() or "",
            model=ModelOut(
                name=model.name,
                version=model.version,
                sha256=model.sha256,
                input_size=model.input_size,
            ),
            image={"width": result.width, "height": result.height},
            threshold=thr,
            iou_threshold=settings.iou_threshold,
            detections=[
                DetectionOut(
                    label=d.label,
                    class_id=d.class_id,
                    score=round(d.score, 6),
                    missing_item=d.label.startswith("No-"),
                    box=Box(
                        x1=round(d.x1, 2), y1=round(d.y1, 2), x2=round(d.x2, 2), y2=round(d.y2, 2)
                    ),
                )
                for d in result.detections
            ],
            timing_ms=timing,
        )

    return app
