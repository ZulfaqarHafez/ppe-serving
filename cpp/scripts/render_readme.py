"""Render the README's result tables from the committed JSON in results/.

Every number in README.md's generated blocks comes from these files:
  results/bench.json        bench/run_bench.py   latency, cold start, memory, machine
  results/parity.json       parity/parity.py     C++ against Python, int8 model
  results/parity_fp32.json  parity/parity.py     the same for the optional fp32 model
  results/fp32_export.json  scripts/export_fp32.py --compare-int8

Blocks are delimited by <!-- BEGIN GENERATED: name --> and
<!-- END GENERATED: name -->. With --check, exits 1 if README.md is not
what this script would write (CI runs that).
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
README = ROOT / "README.md"
STAGE_NAMES = {"decode": "Image decode", "preprocess": "Preprocess (letterbox)",
               "inference": "Inference (model call)", "postprocess": "Postprocess (decode, NMS)",
               "end_to_end": "End to end"}


def load(name):
    path = RESULTS / name
    return json.loads(path.read_text()) if path.exists() else None


def ms(v):
    if v < 1:
        return f"{v:.3f}"
    if v < 10:
        return f"{v:.2f}"
    return f"{v:.1f}"


def ratio(a, b):
    return f"{a / b:.2f}x" if b > 0 else "n/a"


def threads_label(t):
    return "1 thread" if t == 1 else "runtime default threads"


def load_note(load_1min, total_cpus, threads=None):
    note = (f"System load (1-minute load average, sampled before and after every "
            f"process) ranged from {load_1min['min']:.2f} to {load_1min['max']:.2f} "
            f"on {total_cpus} CPUs. The load average lags by about a minute and counts "
            f"this benchmark's own processes, so it rises during the run even on an "
            f"otherwise idle machine.")
    return note


def machine_block(bench):
    m, s, q = bench["machine"], bench["software"], bench["quiet_wait"]
    quiet = (f"the 1-minute load average fell under {q['threshold_load_1min']} after "
             f"{q['waited_minutes']:.0f} min of waiting" if q["quiet"] else
             f"the machine did not go quiet (1-minute load average under "
             f"{q['threshold_load_1min']}) within {q['max_minutes']:.0f} min, so the run went "
             "ahead on a busy machine")
    rows = [
        ("CPU", f"{m['cpu_model']}, {m['logical_cpus']} logical CPUs "
                f"({', '.join(m['isa'])})"),
        ("RAM", f"{m['ram_gib']} GiB"),
        ("OS", f"{m['os']}, kernel {m['kernel']}"),
        ("C++", f"{s['cpp']['compiler']}, {s['cpp']['build_type']} ({s['cpp']['flags']}), "
                f"{s['cpp']['cli']}"),
        ("Python", f"Python {s['python']['version']}, onnxruntime {s['python']['onnxruntime']}, "
                   f"numpy {s['python']['numpy']}, Pillow {s['python']['pillow']}"),
        ("Run", f"{bench['started_utc']} to {bench['finished_utc']} (UTC); {quiet}"),
    ]
    out = ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(out)


def latency_block(bench, model):
    st = bench["settings"]
    out = []
    for entry in (e for e in bench["latency"] if e["model"] == model):
        n = entry["stages_ms"]["cpp"]["end_to_end"]["n"]
        out.append(f"**{model}, {threads_label(entry['threads'])}.** {n} timed iterations per "
                   f"language ({entry['rounds']} alternating rounds of "
                   f"{entry['iterations_per_round']}, after {entry['warmup_per_process']} untimed "
                   f"warm-up iterations in each process), cycling through the five samples. "
                   f"{load_note(entry['load_1min'], bench['machine']['logical_cpus'], entry['threads'])}")
        out.append("")
        out.append("| Stage (ms) | C++ mean | C++ p50 | C++ p95 | C++ p99 | Python mean | "
                   "Python p50 | Python p95 | Python p99 | Python / C++ (p50) |")
        out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for stage, name in STAGE_NAMES.items():
            c, p = entry["stages_ms"]["cpp"][stage], entry["stages_ms"]["python"][stage]
            cells = [ms(c[k]) for k in ("mean", "p50", "p95", "p99")]
            cells += [ms(p[k]) for k in ("mean", "p50", "p95", "p99")]
            label = f"**{name}**" if stage == "end_to_end" else name
            out.append(f"| {label} | " + " | ".join(cells) + f" | {ratio(p['p50'], c['p50'])} |")
        out.append("")
    del st
    return "\n".join(out).rstrip()


def cold_block(bench):
    out = ["| Threads | C++ p50 (p95) ms | Python p50 (p95) ms | Python / C++ (p50) | "
           "C++ peak RSS MiB | Python peak RSS MiB | Runs each | Background load |",
           "|---|---:|---:|---:|---:|---:|---:|---|"]
    for e in bench["cold_start"]:
        c, p = e["first_result_ms"]["cpp"], e["first_result_ms"]["python"]
        rc, rp = e["peak_rss_mib"]["cpp"], e["peak_rss_mib"]["python"]
        out.append(f"| {threads_label(e['threads'])} | {c['p50']:.0f} ({c['p95']:.0f}) | "
                   f"{p['p50']:.0f} ({p['p95']:.0f}) | {ratio(p['p50'], c['p50'])} | "
                   f"{rc['max']:.1f} | {rp['max']:.1f} | {e['runs']} | "
                   f"{e['load_1min']['min']:.2f} to {e['load_1min']['max']:.2f} |")
    e = bench["cold_start"][0]
    out.append("")
    out.append(f"Cold start is the time from fork to the first byte of JSON on stdout for one "
               f"image (`{e['image']}`), so it includes process start, library loading, model "
               f"load and one detection. Peak RSS is the largest `ru_maxrss` over the runs. "
               f"Both are read by `bench/launch.py`, whose own resident size "
               f"({e['launcher_peak_rss_mib']:.1f} MiB) is a floor under the RSS figures.")
    return "\n".join(out)


def parity_block(parity):
    s, t = parity["summary"], parity["tolerances"]
    out = [
        f"- Comparisons: {s['comparisons']} (5 samples x 2 thread settings) on "
        f"`{parity['model']['file']}`, {parity['cpp']} against Python {parity['python']['version']} "
        f"with onnxruntime {parity['python']['onnxruntime']}.",
        f"- Input tensors equal: {s['inputs_equal']} of {s['comparisons']}.",
        f"- Raw outputs bit-identical: {s['outputs_bit_identical']} of {s['comparisons']}; "
        f"largest absolute difference {s['max_output_abs_diff']:.3g} (tolerance {t['output_abs']:g}).",
        f"- Detection lists (thresholds 0.25 and 0.5): {s['detection_lists_bit_identical']} of "
        f"{s['detection_lists']} identical in label, score and box, {s['detections_compared']} "
        f"detections in all; largest score difference {s['max_score_diff']:.3g} (tolerance "
        f"{t['score_abs']:g}), largest box difference {s['max_box_diff_px']:.3g} px (tolerance "
        f"{t['box_px']:g} px).",
    ]
    if "reference_lists" in s:
        out.append(f"- `samples.json` reproduced (labels and scores to 3 decimals, in order): "
                   f"C++ {s['reference_reproduced_cpp']} of {s['reference_lists']} lists, Python "
                   f"{s['reference_reproduced_python']} of {s['reference_lists']}.")
    out.append(f"- Result: {'passed' if s['passed'] else 'FAILED'}.")
    out += ["", "| Sample | C++ at 0.25 | C++ at 0.5 | samples.json at 0.25 |", "|---|---|---|---|"]
    for r in (r for r in parity["runs"] if r["threads"] == 1):
        d = r["detections"]
        ref = ", ".join(d["0.25"].get("reference", [])) or "none"
        out.append(f"| {r['sample']} | {', '.join(d['0.25']['cpp']) or 'none'} | "
                   f"{', '.join(d['0.5']['cpp']) or 'none'} | {ref} |")
    return "\n".join(out)


def describe_diffs(different):
    floats = [d for d in different.values() if d and d["dtype"] == "float32"]
    ints = [d for d in different.values() if d and d["dtype"] != "float32"]
    parts = []
    if floats:
        parts.append(f"{len(floats)} float32 weight scales differ by at most "
                     f"{max(d['max_rel'] for d in floats):.2g} relative (float32 machine epsilon "
                     f"is 1.19e-07)")
    if ints:
        parts.append(f"{len(ints)} quantized weight tensor(s) differ in "
                     f"{sum(d['elements_different'] for d in ints)} element(s) by at most "
                     f"{max(d['max_abs'] for d in ints):.0f} quantization step(s)")
    return ("Of the rest, " + "; ".join(parts) + ".") if parts else ""


def quant_block(parity, parity_fp32, export, bench):
    out = []
    if export:
        f, q = export["fp32"], export["served_int8"]
        init = export["initializers"]
        out.append(f"- Size: fp32 {f['bytes'] / 1e6:.2f} MB, int8 {q['bytes'] / 1e6:.2f} MB "
                   f"({f['bytes'] / q['bytes']:.2f}x smaller).")
        out.append(f"- Provenance check: re-quantizing the reproduced fp32 export with "
                   f"onnxruntime {export['requantized']['onnxruntime']} "
                   f"(`{export['requantized']['method']}`) gives {export['requantized']['bytes']:,} "
                   f"bytes against the served file's {q['bytes']:,} (which also carries a "
                   f"{q['date_metadata_bytes']}-character export `date` that the reproduced "
                   f"export drops); {init['identical']} of {init['requantized']} initializers "
                   f"are identical. {describe_diffs(init['different'])}")
    if bench:
        for t in (1, 0):
            rows = {e["model"]: e for e in bench["latency"] if e["threads"] == t}
            if "int8" in rows and "fp32" in rows:
                i8 = rows["int8"]["stages_ms"]["cpp"]["inference"]["p50"]
                f32 = rows["fp32"]["stages_ms"]["cpp"]["inference"]["p50"]
                out.append(f"- C++ model call p50, {threads_label(t)}: int8 {ms(i8)} ms, fp32 "
                           f"{ms(f32)} ms (int8 / fp32 = {i8 / f32:.2f}).")
    out += ["", "| Sample | int8 at 0.25 | fp32 at 0.25 |", "|---|---|---|"]
    fp = {r["sample"]: r for r in parity_fp32["runs"] if r["threads"] == 1}
    for r in (r for r in parity["runs"] if r["threads"] == 1):
        a = ", ".join(r["detections"]["0.25"]["cpp"]) or "none"
        b = ", ".join(fp[r["sample"]]["detections"]["0.25"]["cpp"]) or "none"
        out.append(f"| {r['sample']} | {a} | {b} |")
    return "\n".join(out)


def blocks():
    bench, parity = load("bench.json"), load("parity.json")
    parity_fp32, export = load("parity_fp32.json"), load("fp32_export.json")
    out = {}
    if bench:
        out["machine"] = machine_block(bench)
        out["latency-int8"] = latency_block(bench, "int8")
        out["latency-fp32"] = (latency_block(bench, "fp32") if any(
            e["model"] == "fp32" for e in bench["latency"]) else "Not measured in this run.")
        out["cold-start"] = cold_block(bench)
    if parity:
        out["parity"] = parity_block(parity)
    if parity and parity_fp32:
        out["quantization"] = quant_block(parity, parity_fp32, export, bench)
    return out


def render(text):
    for name, body in blocks().items():
        pattern = re.compile(rf"(<!-- BEGIN GENERATED: {re.escape(name)} -->).*?"
                             rf"(<!-- END GENERATED: {re.escape(name)} -->)", re.S)
        if not pattern.search(text):
            sys.exit(f"README.md has no block named {name}")
        text = pattern.sub(lambda m, b=body: m.group(1) + "\n" + b + "\n" + m.group(2), text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    current = README.read_text()
    new = render(current)
    if a.check:
        if new != current:
            print("README.md is out of date: run `make readme`", file=sys.stderr)
            return 1
        print("README.md tables match results/*.json")
        return 0
    README.write_text(new)
    print("README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
