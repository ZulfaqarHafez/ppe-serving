"""Summarise k6 results from scripts/loadtest.sh into summary.json and summary.md.

Saturation point (knee): the first concurrency level where doubling the users
adds less than 10 percent throughput but more than 50 percent p95 latency, so
extra users beyond it mostly wait in the queue. The best throughput seen at any
level is reported next to it.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

DESCRIPTIONS = {
    "cpu2-w2t1": "2 CPUs, 2 workers x 1 thread (default)",
    "cpu2-w1t2": "2 CPUs, 1 worker x 2 threads",
    "cpu1-w1t1": "1 CPU, 1 worker x 1 thread (default)",
}


def load(out: Path) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for cfg_dir in sorted(p for p in out.iterdir() if p.is_dir() and p.name != "raw"):
        rows = [json.loads(f.read_text()) for f in cfg_dir.glob("vus-*.json")]
        if rows:
            runs[cfg_dir.name] = sorted(rows, key=lambda r: r["vus"])
    return runs


def saturation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(rows, key=lambda r: r["throughput_rps"])
    knee = rows[-1]
    for cur, nxt in itertools.pairwise(rows):
        gain = nxt["throughput_rps"] / cur["throughput_rps"] - 1
        slower = nxt["latency_ms"]["p95"] / cur["latency_ms"]["p95"] - 1
        if gain < 0.10 and slower > 0.50:
            knee = cur
            break
    return {
        "max_throughput_rps": round(best["throughput_rps"], 2),
        "at_vus": best["vus"],
        "saturation_vus": knee["vus"],
        "saturation_throughput_rps": round(knee["throughput_rps"], 2),
        "saturation_p95_ms": round(knee["latency_ms"]["p95"], 1),
    }


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "results/loadtest")
    machine = json.loads((out / "machine.json").read_text())
    runs = load(out)
    summary: dict[str, Any] = {"machine": machine, "configs": {}}
    lines = [
        "# Load test results",
        "",
        "Produced by `scripts/loadtest.sh` (k6 closed loop, `loadtest/detect.js`, one",
        "640 x 486 WebP sample per request, keep-alive on) and summarised by",
        "`scripts/summarize_loadtest.py`.",
        "",
        f"Machine: {machine['cpu_model']}, {machine['logical_cpus']} logical CPUs, "
        f"{machine['ram_gib']} GiB RAM, kernel {machine['kernel']}, no GPU; Docker "
        f"{machine['docker']}, {machine['k6']}. k6 runs on the same host, outside the "
        "container's CPU limit. Recorded " + machine["recorded_utc"] + ".",
        "",
    ]
    for cfg, rows in runs.items():
        sat = saturation(rows)
        summary["configs"][cfg] = {"runs": rows, "saturation": sat}
        lines += [
            f"## {cfg}: {DESCRIPTIONS.get(cfg, cfg)}",
            "",
            "| VUs | requests | throughput (req/s) | p50 ms | p95 ms | p99 ms | error rate "
            "| load avg before |",
            "|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for r in rows:
            m = re.search(r"loadavg_before=([\d. ]+)", r.get("label", ""))
            lat = r["latency_ms"]
            lines.append(
                f"| {r['vus']} | {r['requests']} | {r['throughput_rps']:.1f} | {lat['p50']:.0f} | "
                f"{lat['p95']:.0f} | {lat['p99']:.0f} | {r['error_rate']:.2%} | "
                f"{m.group(1).strip() if m else ''} |"
            )
        lines += [
            "",
            f"Saturation point: {sat['saturation_vus']} VUs ({sat['saturation_throughput_rps']} "
            f"req/s, p95 {sat['saturation_p95_ms']} ms); doubling the users from there adds under "
            f"10% throughput and over 50% p95. Best throughput at any level: "
            f"{sat['max_throughput_rps']} req/s (at {sat['at_vus']} VUs).",
            "",
        ]
    if {"cpu2-w2t1", "cpu2-w1t2"} <= runs.keys():
        a = summary["configs"]["cpu2-w2t1"]["saturation"]["max_throughput_rps"]
        b = summary["configs"]["cpu2-w1t2"]["saturation"]["max_throughput_rps"]
        diff = (a / b - 1) * 100
        summary["worker_comparison"] = {
            "cpu2_w2t1_max_rps": a,
            "cpu2_w1t2_max_rps": b,
            "w2t1_vs_w1t2_percent": round(diff, 1),
        }
        lines += [
            "## Worker layout under a 2-CPU limit",
            "",
            f"Best throughput with 2 single-threaded workers: {a} req/s; with 1 worker using 2 "
            f"ONNX Runtime threads: {b} req/s; difference {diff:+.1f}%.",
            "",
        ]
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    (out / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
