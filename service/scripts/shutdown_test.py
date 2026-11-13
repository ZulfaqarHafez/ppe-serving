"""Graceful shutdown under load: SIGTERM the container while requests are in flight.

Starts the image with a 2-CPU limit, runs CLIENTS concurrent clients that keep
posting a sample image, sends `docker stop` (SIGTERM, 30 s grace) after
LOAD_SECONDS, and classifies every request:

  ok_before_sigterm      200, finished before SIGTERM
  drained                200, started before SIGTERM and finished after it
  ok_after               200, sent just after `docker stop` was called but before
                         the signal reached the server
  rejected_after_sigterm started after SIGTERM and not served (expected: the
                         listener is closed; through Docker's port proxy this
                         shows as a refused connection or as a disconnect)
  dropped                started before SIGTERM and did not get a 200 (a 5xx, or
                         a connection cut with no response)

Passes when nothing is dropped, at least one request was drained, and the
container exits 0 within the grace period. Writes results/shutdown.json.

Usage: uv run python scripts/shutdown_test.py [image]
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "ppe-service:dev"
NAME = "ppe-shutdown-test"
PORT = 18081
CLIENTS = 16
LOAD_SECONDS = 8.0
SAMPLE = ROOT / "tests" / "data" / "samples" / "site-backs.webp"


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def wait_ready() -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/readyz", timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise SystemExit("service did not become ready")


def main() -> int:
    docker("rm", "-f", NAME)
    started = docker(
        "run", "-d", "--name", NAME, "--cpus", "2", "-p", f"127.0.0.1:{PORT}:8000",
        "-e", "PPE_GRACEFUL_TIMEOUT_S=25", IMAGE,
    )  # fmt: skip
    if started.returncode != 0:
        print(started.stderr)
        return 2
    try:
        wait_ready()
        image = SAMPLE.read_bytes()
        outcomes: list[tuple[str, float, float]] = []
        lock = threading.Lock()
        sigterm_at: list[float] = []
        stop = threading.Event()

        def client() -> None:
            with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=30) as c:
                while not stop.is_set():
                    t0 = time.monotonic()
                    try:
                        r = c.post("/v1/detect", files={"file": ("s.webp", image, "image/webp")})
                        kind = "ok" if r.status_code == 200 else f"http_{r.status_code}"
                    except httpx.ConnectError:
                        kind = "refused"
                    except httpx.HTTPError as exc:
                        kind = f"error_{type(exc).__name__}"
                    t1 = time.monotonic()
                    with lock:
                        outcomes.append((kind, t0, t1))
                    if kind != "ok":
                        time.sleep(0.05)

        threads = [threading.Thread(target=client) for _ in range(CLIENTS)]
        for t in threads:
            t.start()
        time.sleep(LOAD_SECONDS)
        sigterm_at.append(time.monotonic())
        stop_proc = docker("stop", "-t", "30", NAME)
        stopped_at = time.monotonic()
        stop.set()
        for t in threads:
            t.join()
        exit_code = docker("inspect", NAME, "--format", "{{.State.ExitCode}}").stdout.strip()
        logs = docker("logs", NAME).stdout.splitlines()
    finally:
        docker("rm", "-f", NAME)

    sig = sigterm_at[0]
    counts: Counter[str] = Counter()
    for kind, t0, t1 in outcomes:
        if kind == "ok":
            counts["ok_before_sigterm" if t1 < sig else "drained" if t0 < sig else "ok_after"] += 1
        elif t0 >= sig:
            counts["rejected_after_sigterm"] += 1
            counts[f"rejected_after_sigterm_{kind}"] += 1
        else:
            counts["dropped"] += 1
            counts[f"dropped_{kind}"] += 1
    events = [json.loads(ln) for ln in logs if ln.startswith("{")]
    shutdown_msgs = [
        e["msg"] for e in events if e.get("logger") in ("ppe_service", "uvicorn.error")
    ]
    result = {
        "image": IMAGE,
        "cpus": 2,
        "clients": CLIENTS,
        "load_seconds_before_sigterm": LOAD_SECONDS,
        "docker_stop_seconds": round(stopped_at - sig, 2),
        "docker_stop_returncode": stop_proc.returncode,
        "container_exit_code": int(exit_code) if exit_code.isdigit() else exit_code,
        "requests": len(outcomes),
        "outcomes": dict(sorted(counts.items())),
        "server_shutdown_log": [m for m in shutdown_msgs if m not in ("request",)][-6:],
        "passed": counts["dropped"] == 0 and counts["drained"] > 0 and exit_code == "0",
    }
    out = ROOT / "results" / "shutdown.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
