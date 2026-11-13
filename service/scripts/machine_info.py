"""Print the machine details the load-test results are tied to, as JSON.

CPU model and logical cores from /proc/cpuinfo, RAM from /proc/meminfo, kernel
from uname, and tool versions. No hostnames or paths.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False).stdout
    except OSError:
        return "not installed"
    return out.strip().splitlines()[0] if out.strip() else "unknown"


def collect() -> dict[str, object]:
    cpuinfo = Path("/proc/cpuinfo").read_text()
    models = [
        ln.split(":", 1)[1].strip() for ln in cpuinfo.splitlines() if ln.startswith("model name")
    ]
    mem_kb = next(
        int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()
        if ln.startswith("MemTotal:")
    )  # fmt: skip
    return {
        "recorded_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cpu_model": models[0] if models else "unknown",
        "logical_cpus": len(models) or os.cpu_count(),
        "ram_gib": round(mem_kb / 1024 / 1024, 1),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "gpu": "none",
        "docker": _version(["docker", "version", "--format", "{{.Server.Version}}"]),
        "k6": _version(["k6", "version"]),
        "note": "virtual machine; the load generator runs on the same host as the service",
    }


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, indent=1)
    sys.stdout.write("\n")
