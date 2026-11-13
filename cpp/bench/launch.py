"""Small launcher for the cold-start measurement. Run as: python3 -I -S launch.py CMD...

Forks and execs CMD with stdout on a pipe, and prints one JSON line:
  first_output_ms  fork to the first byte CMD writes to stdout
  exit_ms          fork to CMD's exit
  peak_rss_kib     CMD's peak resident set size (ru_maxrss from wait4)
  launcher_rss_kib this launcher's own peak RSS (VmHWM) when it forks

Why a launcher: Linux carries the parent's resident size into a forked child's
ru_maxrss (the child starts as a copy of the parent). Started from the
benchmark driver, which has numpy and onnxruntime loaded, every child would
report at least the driver's size. This launcher imports nothing heavy, so
the floor it adds is its own small size, reported as launcher_rss_kib.
"""
import json
import os
import sys
import time


def vm_hwm_kib() -> int:
    """Peak RSS of this process's own memory map. (ru_maxrss would include the
    size inherited from whoever started this launcher.)"""
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    return -1


def main() -> int:
    cmd = sys.argv[1:]
    read_fd, write_fd = os.pipe()
    own = vm_hwm_kib()
    t0 = time.perf_counter()
    pid = os.fork()
    if pid == 0:
        os.dup2(write_fd, 1)
        os.close(read_fd)
        os.close(write_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        try:
            os.execv(cmd[0], cmd)
        finally:
            os._exit(127)
    os.close(write_fd)
    first = os.read(read_fd, 1)
    t1 = time.perf_counter()
    chunks = [first]
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(read_fd)
    _, status, usage = os.wait4(pid, 0)
    t2 = time.perf_counter()
    out = b"".join(chunks)
    print(json.dumps({
        "exit_code": os.waitstatus_to_exitcode(status),
        "first_output_ms": (t1 - t0) * 1000,
        "exit_ms": (t2 - t0) * 1000,
        "peak_rss_kib": usage.ru_maxrss,
        "launcher_rss_kib": own,
        "output_ok": b'"detections"' in out,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
