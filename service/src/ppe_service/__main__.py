"""Entry point: verify the model checksum, load it, then serve.

Exit codes: 2 model file or manifest missing, 3 checksum mismatch, 4 bad config.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from .config import Settings
from .engine import Detector, ModelInfo, load_session
from .logs import configure_logging
from .registry import ChecksumMismatchError, ModelManifest, verify_file

log = logging.getLogger("ppe_service")


def build(settings: Settings) -> tuple[Detector, int]:
    manifest = ModelManifest.load(settings.manifest_path)
    expected = settings.model_sha256 or manifest.sha256
    sha = verify_file(settings.model_path, expected)
    log.info("model checksum verified", extra={"path": settings.model_path.name, "sha256": sha})
    session = load_session(settings.model_path, settings.intra_op_threads)
    detector = Detector(
        session,
        ModelInfo(manifest.name, manifest.version, sha, settings.input_size),
        allowed_formats=settings.allowed_formats,
        max_pixels=settings.max_pixels,
        iou_threshold=settings.iou_threshold,
    )
    detector.warm_up()
    return detector, settings.resolved_workers


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        configure_logging("INFO")
        log.error("bad configuration", extra={"error": str(exc)})
        return 4
    configure_logging(settings.log_level)
    try:
        detector, workers = build(settings)
    except FileNotFoundError as exc:
        log.error("model or manifest missing", extra={"error": str(exc)})
        return 2
    except ChecksumMismatchError as exc:
        log.error("model checksum mismatch, refusing to start", extra={"error": str(exc)})
        return 3

    from .app import create_app

    app = create_app(settings, detector.detect, detector.info, workers=workers)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        http="httptools",
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=int(settings.graceful_timeout_s),
        timeout_keep_alive=5,
        server_header=False,
    )
    uvicorn.Server(config).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
