"""Fetch the model named in registry/manifest.json and refuse it unless its SHA-256 matches.

Usage:
    python scripts/fetch_model.py [--manifest registry/manifest.json]
                                  [--source LOCATION] [--dest models/<filename>]
    python scripts/fetch_model.py --verify-only models/ppe_yolov8s_320_int8dyn.onnx

LOCATION is a local path, a file:// URL or an http(s):// URL; the default is the
manifest's artifact.source (the public URL). The file is downloaded to a
temporary name next to the destination, hashed, and only renamed into place if
the hash matches. Exit code 0 on success, 1 on a checksum mismatch, 2 on any
other failure. Behind a TLS-intercepting proxy, point SSL_CERT_FILE at its CA.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ppe_service.registry import ModelManifest, sha256_file

_CHUNK = 1 << 20


class _Readable(Protocol):
    def read(self, n: int = -1, /) -> bytes: ...

    def close(self) -> None: ...


def _open(location: str) -> tuple[_Readable, str]:
    """Return a readable binary stream for a path, file:// or http(s):// location."""
    parsed = urllib.parse.urlparse(location)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(location, headers={"User-Agent": "ppe-fetch-model/1"})
        return urllib.request.urlopen(request, timeout=60), location
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path))
    elif parsed.scheme in ("", "local") or len(parsed.scheme) == 1:
        path = Path(location)
    else:
        raise ValueError(f"unsupported location scheme {parsed.scheme!r}")
    return path.open("rb"), str(path)


def fetch(location: str, dest: Path, expected_sha256: str, expected_size: int | None) -> str:
    """Copy ``location`` to ``dest`` if and only if its SHA-256 is ``expected_sha256``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256_file(dest) == expected_sha256:
        print(f"{dest.name}: already present, SHA-256 verified")
        return expected_sha256
    stream, shown = _open(location)
    h = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, contextlib.closing(stream) as src:
            while chunk := src.read(_CHUNK):
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        actual = h.hexdigest()
        if actual != expected_sha256:
            raise ChecksumError(
                f"refusing {shown}: SHA-256 {actual} != pinned {expected_sha256} ({size} bytes)"
            )
        if expected_size is not None and size != expected_size:
            raise ChecksumError(f"refusing {shown}: {size} bytes, manifest says {expected_size}")
        tmp.chmod(0o644)
        shutil.move(str(tmp), dest)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{dest.name}: {size} bytes from {shown}, SHA-256 {actual} verified")
    return actual


class ChecksumError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=root / "registry" / "manifest.json")
    parser.add_argument("--source", help="local path, file:// or http(s):// URL")
    parser.add_argument("--dest", type=Path, help="where to put the model")
    parser.add_argument("--sha256", help="override the manifest's pinned SHA-256")
    parser.add_argument("--verify-only", type=Path, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        manifest = ModelManifest.load(args.manifest)
        expected = (args.sha256 or manifest.sha256).lower()
        if args.verify_only:
            actual = sha256_file(args.verify_only)
            if actual != expected:
                print(f"{args.verify_only.name}: SHA-256 {actual} != pinned {expected}")
                return 1
            print(f"{args.verify_only.name}: SHA-256 {actual} verified")
            return 0
        dest = args.dest or root / "models" / manifest.filename
        size = None if args.sha256 else manifest.size_bytes
        fetch(args.source or manifest.source, dest, expected, size)
    except ChecksumError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
