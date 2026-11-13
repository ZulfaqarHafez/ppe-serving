"""Benchmark driver: C++ against Python onnxruntime on the same model and images.

1. Waits for a quiet machine: checks the 1-minute load average every
   --check-seconds until it is under --quiet-load, for at most --wait-minutes.
   It runs whether or not the machine went quiet, and records which.
2. Latency: for each model and each thread setting (1 intra-op thread, and
   the onnxruntime default), runs --rounds rounds; each round runs the C++
   harness (ppe_bench) and the Python harness (bench_py.py) once each, in
   alternating order (C++ first in even rounds, Python first in odd ones).
   Each harness process does --warmup untimed iterations, then --iterations
   timed ones cycling through the five samples. Samples from all rounds are
   pooled per stage: mean, p50, p95, p99 (numpy.percentile, linear).
3. Cold start: runs the CLIs (ppe_detect and detect_py.py) on one image,
   alternating, --cold-runs times each per thread setting after one untimed
   run each, through bench/launch.py, which times fork to the first byte of
   output on stdout and reads the process's peak resident set size from
   wait4() (see launch.py for why a launcher is needed).
4. Writes everything, with the machine and software details and the load
   average before and after every process, to --out.

Usage: python3 bench/run_bench.py --cli build/release-clang/ppe_detect \
         --bench build/release-clang/ppe_bench \
         --model .cache/models/ppe_yolov8s_320_int8dyn.onnx --out results/bench.json
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLES = ["site-backs", "rooftop-cctv", "plant-cctv", "hi-vis-walk", "packing-cctv"]
STAGES = ["decode", "preprocess", "inference", "postprocess", "end_to_end"]
THREADS = [1, 0]


def loadavg():
    with open("/proc/loadavg") as f:
        return [float(v) for v in f.read().split()[:3]]


def machine():
    cpuinfo = pathlib.Path("/proc/cpuinfo").read_text()
    meminfo = pathlib.Path("/proc/meminfo").read_text()
    model = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
    flags = re.search(r"^flags\s*:\s*(.+)$", cpuinfo, re.M)
    flagset = set(flags.group(1).split()) if flags else set()
    mem_kb = int(re.search(r"^MemTotal:\s*(\d+) kB", meminfo, re.M).group(1))
    return {
        "cpu_model": model.group(1).strip() if model else platform.processor(),
        "logical_cpus": len(re.findall(r"^processor\s*:", cpuinfo, re.M)),
        "cpus_usable": len(os.sched_getaffinity(0)),
        "ram_gib": round(mem_kb / 1024 / 1024, 1),
        "isa": sorted(f for f in ("avx2", "avx512f", "avx512_vnni", "avx_vnni", "fma") if f in flagset),
        "kernel": platform.release(),
        "os": platform.freedesktop_os_release().get("PRETTY_NAME", "") if hasattr(
            platform, "freedesktop_os_release") else "",
    }


def software(cli, build_dir):
    cache = (build_dir / "CMakeCache.txt").read_text()

    def cache_var(name):
        m = re.search(rf"^{name}:[A-Z]+=(.*)$", cache, re.M)
        return m.group(1) if m else ""

    compiler = cache_var("CMAKE_CXX_COMPILER")
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True).stdout
    build_type = cache_var("CMAKE_BUILD_TYPE")
    import onnxruntime as ort
    import PIL

    return {
        "cpp": {
            "compiler": version.splitlines()[0] if version else compiler,
            "build_type": build_type,
            "flags": cache_var(f"CMAKE_CXX_FLAGS_{build_type.upper()}"),
            "cli": subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip(),
        },
        "python": {"version": platform.python_version(), "onnxruntime": ort.__version__,
                   "numpy": np.__version__, "pillow": PIL.__version__},
    }


def wait_for_quiet(threshold, max_minutes, check_seconds):
    start = time.monotonic()
    checks = []
    while True:
        load = loadavg()
        elapsed = (time.monotonic() - start) / 60
        checks.append({"minute": round(elapsed, 2), "load_1min": load[0]})
        print(f"[quiet] {elapsed:5.1f} min: load {load[0]:.2f}", flush=True)
        if load[0] < threshold:
            return {"quiet": True, "waited_minutes": round(elapsed, 2), "checks": checks}
        if elapsed + check_seconds / 60 > max_minutes:
            return {"quiet": False, "waited_minutes": round(elapsed, 2), "checks": checks}
        time.sleep(check_seconds)


def stats(values):
    v = np.asarray(values, dtype=np.float64)
    return {"n": int(v.size), "mean": float(v.mean()), "p50": float(np.percentile(v, 50)),
            "p95": float(np.percentile(v, 95)), "p99": float(np.percentile(v, 99)),
            "min": float(v.min()), "max": float(v.max())}


def run_json(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"{cmd[0]} failed ({res.returncode}): {res.stderr}")
    return json.loads(res.stdout)


def latency(a, model, threads, images):
    cmds = {
        "cpp": [a.bench, "--model", model, "--threads", str(threads), "--warmup", str(a.warmup),
                "--iterations", str(a.iterations)] + images,
        "python": [sys.executable, str(HERE / "bench_py.py"), "--model", model, "--threads",
                   str(threads), "--warmup", str(a.warmup), "--iterations", str(a.iterations)]
                  + images,
    }
    pooled = {lang: {s: [] for s in STAGES} for lang in cmds}
    detections = {lang: 0 for lang in cmds}
    loads = []
    for r in range(a.rounds):
        order = ["cpp", "python"] if r % 2 == 0 else ["python", "cpp"]
        for lang in order:
            before = loadavg()[0]
            out = run_json(cmds[lang])
            after = loadavg()[0]
            loads.append({"round": r, "language": lang, "before": before, "after": after})
            detections[lang] += out["detections"]
            for s in STAGES:
                pooled[lang][s].extend(out["stages_ms"][s])
        print(f"  round {r + 1}/{a.rounds} ({'/'.join(order)}): load {loadavg()[0]:.2f}", flush=True)
    return {
        "threads": threads,
        "rounds": a.rounds,
        "iterations_per_round": a.iterations,
        "warmup_per_process": a.warmup,
        "detections": detections,
        "load_1min": {"min": min(min(x["before"], x["after"]) for x in loads),
                      "max": max(max(x["before"], x["after"]) for x in loads),
                      "per_process": loads},
        "stages_ms": {lang: {s: stats(pooled[lang][s]) for s in STAGES} for lang in pooled},
    }


def first_output(cmd):
    """Run cmd through bench/launch.py: milliseconds from fork to the first
    stdout byte, peak RSS in MiB, and the launcher's own peak RSS in MiB."""
    res = run_json([sys.executable, "-I", "-S", str(HERE / "launch.py")] + cmd)
    if res["exit_code"] != 0 or not res["output_ok"]:
        sys.exit(f"{cmd[0]} failed with exit code {res['exit_code']}")
    return res["first_output_ms"], res["peak_rss_kib"] / 1024, res["launcher_rss_kib"] / 1024


def cold_start(a, model, threads, image):
    cmds = {
        "cpp": [str(pathlib.Path(a.cli).resolve()), "--model", model, "--threads", str(threads),
                image],
        "python": [sys.executable, str(HERE / "detect_py.py"), "--model", model, "--threads",
                   str(threads), image],
    }
    for cmd in cmds.values():
        first_output(cmd)  # one untimed run each: page cache and dynamic loader warm
    times = {k: [] for k in cmds}
    rss = {k: [] for k in cmds}
    launcher = []
    loads = []
    for r in range(a.cold_runs):
        for lang in (["cpp", "python"] if r % 2 == 0 else ["python", "cpp"]):
            before = loadavg()[0]
            ms, mib, launcher_mib = first_output(cmds[lang])
            loads.append(before)
            launcher.append(launcher_mib)
            times[lang].append(ms)
            rss[lang].append(mib)
    return {
        "threads": threads,
        "runs": a.cold_runs,
        "image": pathlib.Path(image).name,
        "load_1min": {"min": min(loads), "max": max(loads)},
        "first_result_ms": {k: stats(v) for k, v in times.items()},
        "peak_rss_mib": {k: stats(v) for k, v in rss.items()},
        "launcher_peak_rss_mib": max(launcher),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--fp32-model")
    ap.add_argument("--samples", default=str(ROOT / "data" / "samples"))
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--cold-runs", type=int, default=20)
    ap.add_argument("--quiet-load", type=float, default=0.5)
    ap.add_argument("--wait-minutes", type=float, default=40)
    ap.add_argument("--check-seconds", type=float, default=60)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    images = [str(pathlib.Path(a.samples) / f"{sid}.png") for sid in SAMPLES]
    models = {"int8": a.model}
    if a.fp32_model:
        models["fp32"] = a.fp32_model
    started = datetime.datetime.now(datetime.timezone.utc)
    quiet = wait_for_quiet(a.quiet_load, a.wait_minutes, a.check_seconds)
    report = {
        "generated_by": "bench/run_bench.py",
        "started_utc": started.isoformat(timespec="seconds"),
        "machine": machine(),
        "software": software(a.cli, pathlib.Path(a.cli).resolve().parent),
        "models": {k: {"file": pathlib.Path(v).name,
                       "sha256": hashlib.sha256(pathlib.Path(v).read_bytes()).hexdigest()}
                   for k, v in models.items()},
        "settings": {"rounds": a.rounds, "iterations_per_round": a.iterations,
                     "warmup_per_process": a.warmup, "cold_runs": a.cold_runs,
                     "score_threshold": 0.25, "iou_threshold": 0.7,
                     "images": [pathlib.Path(p).name for p in images],
                     "threads": "1 = intra-op 1 and inter-op 1; 0 = onnxruntime defaults; "
                                "the same in C++ and Python"},
        "quiet_wait": {"threshold_load_1min": a.quiet_load, "max_minutes": a.wait_minutes,
                       "check_seconds": a.check_seconds, **quiet},
        "latency": [],
        "cold_start": [],
    }
    for name, model in models.items():
        for threads in THREADS:
            print(f"latency: {name}, threads={threads}", flush=True)
            report["latency"].append({"model": name, **latency(a, model, threads, images)})
    for threads in THREADS:
        print(f"cold start: threads={threads}", flush=True)
        report["cold_start"].append({"model": "int8", **cold_start(a, a.model, threads, images[0])})
    report["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(report, indent=1) + "\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
