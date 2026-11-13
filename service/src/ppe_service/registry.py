"""Model registry manifest and checksum checks, shared by the server and fetch_model.py."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


class ChecksumMismatchError(RuntimeError):
    """The model file's SHA-256 is not the one the manifest pins."""


@dataclass(frozen=True, slots=True)
class ModelManifest:
    name: str
    version: str
    sha256: str
    size_bytes: int
    filename: str
    source: str
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> ModelManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: manifest must be a JSON object")
        validate_manifest(data)
        artifact = data["artifact"]
        return cls(
            name=str(data["name"]),
            version=str(data["version"]),
            sha256=str(artifact["sha256"]).lower(),
            size_bytes=int(artifact["size_bytes"]),
            filename=str(artifact["filename"]),
            source=str(artifact["source"]),
            raw=data,
        )


_REQUIRED: dict[str, type] = {
    "name": str,
    "version": str,
    "artifact": dict,
    "lineage": dict,
    "licence": dict,
    "metrics": dict,
    "io": dict,
}


def validate_manifest(data: dict[str, Any]) -> None:
    """Raise ValueError if a manifest misses a required field or has a malformed hash."""
    for key, kind in _REQUIRED.items():
        if not isinstance(data.get(key), kind):
            raise ValueError(f"manifest field {key!r} missing or not a {kind.__name__}")
    artifact = data["artifact"]
    for key in ("filename", "sha256", "size_bytes", "source"):
        if key not in artifact:
            raise ValueError(f"manifest artifact.{key} missing")
    digest = str(artifact["sha256"])
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise ValueError("manifest artifact.sha256 must be 64 hex characters")
    if not isinstance(data["metrics"].get("source"), dict):
        raise ValueError("manifest metrics.source must say which file the numbers come from")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, expected_sha256: str) -> str:
    """Return the file's SHA-256, or raise ChecksumMismatchError if it is not ``expected``."""
    actual = sha256_file(path)
    if actual != expected_sha256.lower():
        raise ChecksumMismatchError(
            f"{path.name}: SHA-256 {actual} does not match the pinned {expected_sha256.lower()}"
        )
    return actual
