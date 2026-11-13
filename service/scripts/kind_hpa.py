"""HPA under load on the kind cluster, with and without HTTP keep-alive.

For each mode: wait until the deployment is back at one ready pod, run k6
(VUS users for DURATION) from the host against the NodePort, so every
connection goes through kube-proxy, and every SAMPLE_S seconds record the HPA
(replicas, CPU) and each pod's count of successful /v1/detect requests, read
from the pod's own /metrics through the API server proxy.

kube-proxy balances connections, not requests. With keep-alive, k6 opens its
connections once, to the only pod there is, and keeps them; pods the HPA adds
later receive almost nothing. Without keep-alive every request is a new
connection and is spread over the ready pods.

Writes results/k8s/hpa-<mode>.json and results/k8s/hpa.md.
Usage: python3 scripts/kind_hpa.py   (after scripts/kind_up.sh)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "k8s"
NS = "ppe"
VUS = int(os.environ.get("VUS", "8"))
DURATION_S = int(os.environ.get("DURATION_S", "150"))
SAMPLE_S = 10
COUNTER = re.compile(
    r"^ppe_http_requests_total\{"
    r'(?=[^}]*route="/v1/detect")(?=[^}]*status="200")[^}]*\} (\S+)$',
    re.M,
)
NO_PROXY_ENV = {
    k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")
}


def kubectl(*args: str) -> str:
    return subprocess.run(
        ["kubectl", "-n", NS, *args], capture_output=True, text=True, check=True, timeout=30
    ).stdout


def pods() -> list[dict[str, Any]]:
    data = json.loads(
        kubectl("get", "pods", "-l", "app.kubernetes.io/name=ppe-service", "-o", "json")
    )
    out = []
    for p in data["items"]:
        ready = any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in p["status"].get("conditions", [])
        )
        out.append(
            {
                "name": p["metadata"]["name"],
                "phase": p["status"].get("phase"),
                "ready": ready,
                "deleting": "deletionTimestamp" in p["metadata"],
            }
        )
    return out


def served(pod: str) -> int | None:
    try:
        text = kubectl("get", "--raw", f"/api/v1/namespaces/{NS}/pods/{pod}:8000/proxy/metrics")
    except subprocess.CalledProcessError:
        return None
    m = COUNTER.search(text)
    return int(float(m.group(1))) if m else 0


def hpa() -> dict[str, Any]:
    h = json.loads(kubectl("get", "hpa", "ppe-service", "-o", "json"))
    cpu = next(
        (
            m["resource"]["current"].get("averageUtilization")
            for m in h["status"].get("currentMetrics") or []
            if m.get("type") == "Resource"
        ),
        None,
    )
    return {
        "current_replicas": h["status"].get("currentReplicas"),
        "desired_replicas": h["status"].get("desiredReplicas"),
        "cpu_utilization_percent": cpu,
    }


def wait_for_one_pod(timeout_s: int = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ps = [p for p in pods() if not p["deleting"]]
        if len(ps) == 1 and ps[0]["ready"] and hpa()["current_replicas"] == 1:
            return
        time.sleep(5)
    raise SystemExit("deployment did not scale back to one pod")


def node_ip() -> str:
    return subprocess.run(
        ["docker", "inspect", "ppe-control-plane", "-f",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


def run_mode(keepalive: bool, url: str) -> dict[str, Any]:
    mode = "keepalive" if keepalive else "no-keepalive"
    wait_for_one_pod()
    baseline = {p["name"]: served(p["name"]) or 0 for p in pods()}
    load_before = Path("/proc/loadavg").read_text().split()[:3]
    samples: list[dict[str, Any]] = []
    stop = threading.Event()
    t_start = time.monotonic()

    def take_sample() -> None:
        ps = pods()
        samples.append(
            {
                "t_s": round(time.monotonic() - t_start),
                **hpa(),
                "pods": {
                    p["name"]: {
                        "ready": p["ready"],
                        "served": (served(p["name"]) or 0) - baseline.get(p["name"], 0),
                    }
                    for p in ps
                    if not p["deleting"]
                },
            }
        )

    def sampler() -> None:
        while not stop.is_set():
            take_sample()
            stop.wait(SAMPLE_S)

    th = threading.Thread(target=sampler)
    th.start()
    summary_path = OUT / f"hpa-{mode}-k6.json"
    k6 = subprocess.run(
        ["k6", "run", "-q", "-e", f"BASE_URL={url}", "-e", f"VUS={VUS}",
         "-e", f"DURATION={DURATION_S}s", "-e", f"KEEPALIVE={1 if keepalive else 0}",
         "-e", f"LABEL=kind HPA {mode}", "-e", f"SUMMARY={summary_path}",
         str(ROOT / "loadtest" / "detect.js")],
        capture_output=True, text=True, env=NO_PROXY_ENV, check=False, cwd=ROOT,
    )  # fmt: skip
    stop.set()
    th.join()
    take_sample()  # after k6 has finished, so per-pod totals cover the whole run
    final = samples[-1]["pods"]
    total = sum(p["served"] for p in final.values()) or 1
    shares = {
        name: round(p["served"] / total, 3)
        for name, p in sorted(final.items(), key=lambda kv: -kv[1]["served"])
    }
    k6_summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    result = {
        "mode": mode,
        "host_loadavg_before": load_before,
        "vus": VUS,
        "duration_s": DURATION_S,
        "k6_exit_code": k6.returncode,
        "k6": k6_summary,
        "max_replicas_seen": max(s["current_replicas"] or 0 for s in samples),
        "requests_served_per_pod": {n: p["served"] for n, p in final.items()},
        "share_per_pod": shares,
        "busiest_pod_share": max(shares.values()),
        "samples": samples,
    }
    (OUT / f"hpa-{mode}.json").write_text(json.dumps(result, indent=1) + "\n")
    summary_path.unlink(missing_ok=True)
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    url = f"http://{node_ip()}:30080"
    results = [run_mode(True, url), run_mode(False, url)]
    lines = [
        "# HPA on kind: keep-alive against no keep-alive",
        "",
        f"Produced by `scripts/kind_hpa.py`: k6 with {VUS} users for {DURATION_S} s from the host",
        "against the NodePort (so through kube-proxy), one kind node on the machine in",
        "`results/loadtest/machine.json`. Pod CPU request 500m, limit 1; HPA target 60% CPU,",
        "1 to 4 replicas. Raw samples every 10 s are in `hpa-keepalive.json` and",
        "`hpa-no-keepalive.json`.",
        "",
        "| mode | requests | throughput (req/s) | p95 ms | error rate | max replicas | "
        "busiest pod share | requests per pod |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        k = r["k6"]
        per_pod = ", ".join(
            str(v) for v in sorted(r["requests_served_per_pod"].values(), reverse=True)
        )
        lines.append(
            f"| {r['mode']} | {k.get('requests', 0)} | {k.get('throughput_rps', 0):.1f} | "
            f"{k.get('latency_ms', {}).get('p95', 0):.0f} | {k.get('error_rate', 0):.2%} | "
            f"{r['max_replicas_seen']} | {r['busiest_pod_share']:.1%} | {per_pod} |"
        )
    lines += ["", "Replicas over time (seconds since the load started):", ""]
    for r in results:
        timeline = ", ".join(
            f"{s['t_s']}s: {s['current_replicas']} ({s['cpu_utilization_percent']}% CPU)"
            for s in r["samples"]
        )
        lines.append(f"- {r['mode']}: {timeline}")
    (OUT / "hpa.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
