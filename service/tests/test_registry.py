"""Registry manifest, checksum checks and scripts/fetch_model.py."""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import fetch_model
from ppe_service.registry import (
    ChecksumMismatchError,
    ModelManifest,
    validate_manifest,
    verify_file,
)

from .conftest import MANIFEST

PAYLOAD = b"not really a model, but bytes with a known hash\n"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _manifest(tmp_path: Path, source: str, sha: str = PAYLOAD_SHA) -> Path:
    data: dict[str, Any] = json.loads(MANIFEST.read_text())
    data["artifact"].update(
        {"sha256": sha, "size_bytes": len(PAYLOAD), "source": source, "filename": "m.onnx"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path


def test_committed_manifest_is_valid_and_cites_the_eval_file() -> None:
    m = ModelManifest.load(MANIFEST)
    assert m.filename == "ppe_yolov8s_320_int8dyn.onnx"
    assert m.sha256 == "d0a6c62f4bda6733f443b22bf9dce288b8f082ca0fc2f404a4931eb7cf0cbac2"
    assert m.source.startswith("https://")
    metrics = m.raw["metrics"]
    assert metrics["source"]["file"] == "eval/results/onnx_export.json"
    assert metrics["source"]["key"] == "variants.int8dyn_320"
    assert metrics["test_map50"] == 0.4135
    assert m.raw["io"]["classes"] == [
        "Gloves", "Helmet", "No-Helmet", "No-gloves", "No-vest", "Vest"
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.pop("lineage"), "lineage"),
        (lambda d: d["artifact"].update(sha256="xyz"), "64 hex"),
        (lambda d: d["artifact"].pop("source"), "source"),
        (lambda d: d["metrics"].pop("source"), "metrics.source"),
    ],
)
def test_validate_manifest_rejects(mutate: Any, message: str) -> None:
    data = json.loads(MANIFEST.read_text())
    mutate(data)
    with pytest.raises(ValueError, match=message):
        validate_manifest(data)


def test_verify_file(tmp_path: Path) -> None:
    f = tmp_path / "m.onnx"
    f.write_bytes(PAYLOAD)
    assert verify_file(f, PAYLOAD_SHA.upper()) == PAYLOAD_SHA
    with pytest.raises(ChecksumMismatchError):
        verify_file(f, "0" * 64)


def test_fetch_from_local_path_and_file_url(tmp_path: Path) -> None:
    src = tmp_path / "src.onnx"
    src.write_bytes(PAYLOAD)
    manifest = _manifest(tmp_path, str(src))
    dest = tmp_path / "out" / "m.onnx"
    assert fetch_model.main(["--manifest", str(manifest), "--dest", str(dest)]) == 0
    assert dest.read_bytes() == PAYLOAD
    dest.unlink()
    rc = fetch_model.main(
        ["--manifest", str(manifest), "--source", src.as_uri(), "--dest", str(dest)]
    )
    assert rc == 0
    assert dest.read_bytes() == PAYLOAD
    assert fetch_model.main(["--manifest", str(manifest), "--verify-only", str(dest)]) == 0


def test_fetch_refuses_mismatch_and_leaves_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src.onnx"
    src.write_bytes(PAYLOAD + b"tampered")
    manifest = _manifest(tmp_path, str(src))
    out = tmp_path / "out"
    rc = fetch_model.main(["--manifest", str(manifest), "--dest", str(out / "m.onnx")])
    assert rc == 1
    assert list(out.iterdir()) == []
    assert fetch_model.main(["--manifest", str(manifest), "--verify-only", str(src)]) == 1


def test_fetch_missing_source_is_error_2(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, str(tmp_path / "absent.onnx"))
    assert fetch_model.main(["--manifest", str(manifest), "--dest", str(tmp_path / "x")]) == 2


def test_fetch_unknown_scheme_is_error_2(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, "ftp://example.invalid/m.onnx")
    assert fetch_model.main(["--manifest", str(manifest), "--dest", str(tmp_path / "x")]) == 2


@pytest.fixture
def http_server(tmp_path: Path) -> Iterator[str]:
    root = tmp_path / "www"
    root.mkdir()
    (root / "m.onnx").write_bytes(PAYLOAD)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/m.onnx"
    server.shutdown()
    server.server_close()


def test_fetch_over_http(tmp_path: Path, http_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    manifest = _manifest(tmp_path, http_server)
    dest = tmp_path / "m.onnx"
    assert fetch_model.main(["--manifest", str(manifest), "--dest", str(dest)]) == 0
    assert dest.read_bytes() == PAYLOAD
    bad = _manifest(tmp_path, http_server, sha="1" * 64)
    dest.unlink()
    assert fetch_model.main(["--manifest", str(bad), "--dest", str(dest)]) == 1
    assert not dest.exists()
