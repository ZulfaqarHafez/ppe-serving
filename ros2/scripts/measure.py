"""
Measure the detector node and the detection-to-goal path on this machine.

Writes results/benchmark.json and results/benchmark.md. Every number comes from
this run; nothing is estimated. Run from the repository root after
`colcon build` with the workspace sourced:

    python3 scripts/measure.py [--window 30]

Scenarios
  detector_*: the detector node alone (autostart), fed by the replay publisher
    cycling the five sample images. "saturated" offers 50 frames/s, more than
    the node can take, so frames/s is its throughput (the subscription keeps
    only the newest frame). "5hz" offers 5 frames/s, the simulated camera rate,
    for latency without queueing. Latency is image header stamp (set just
    before publish) to the moment this script receives the Detection2DArray,
    so it includes two DDS hops and this script's Python callback. CPU is the
    detector process's user+system time over the window divided by wall time
    (100 percent = one core).
  e2e: replay_demo.launch.py on plant-cctv at 5 frames/s with the fake
    NavigateToPose server, patrol cooldown 1 s. For every goal the patrol node
    sends, "trigger" is image stamp of the frame that completed the run of 3
    to the goal being sent, and "first frame" is stamp of the first frame of
    the run to the goal being sent (includes waiting for 3 frames at 5 Hz).
"""
import argparse
import datetime
import glob
import json
import os
import platform
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float64MultiArray, String
from vision_msgs.msg import Detection2DArray

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, 'install')
SAMPLES = 'site-backs,rooftop-cctv,plant-cctv,hi-vis-walk,packing-cctv'


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return ''


def machine():
    lscpu = {k.strip(): v.strip() for k, v in
             (line.split(':', 1) for line in sh('lscpu').splitlines() if ':' in line)}
    mem_kb = int(sh("awk '/MemTotal/ {print $2}' /proc/meminfo") or 0)
    ort = [os.path.basename(p) for p in
           glob.glob('/opt/ros/*/opt/onnxruntime_vendor/lib/libonnxruntime.so.*.*.*')]
    return {
        'cpu_model': lscpu.get('Model name', ''),
        'logical_cpus': os.cpu_count(),
        'threads_per_core': lscpu.get('Thread(s) per core', ''),
        'cpu_flags_avx512_vnni': 'avx512_vnni' in lscpu.get('Flags', ''),
        'ram_gib': round(mem_kb / 1024 / 1024, 1),
        'os': sh('. /etc/os-release && echo $PRETTY_NAME'),
        'kernel': platform.release(),
        'ros_distro': os.environ.get('ROS_DISTRO', ''),
        'onnxruntime': ort[0].replace('libonnxruntime.so.', '') if ort else '',
        'gpu': 'none used (CPU execution provider)',
        'date_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M'),
    }


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def cpu_seconds(pid):
    with open(f'/proc/{pid}/stat') as f:
        fields = f.read().rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


class Collector:
    def __init__(self):
        self.node = rclpy.create_node('measure')
        self.lock = threading.Lock()
        self.recording = False
        self.det = []      # (latency_ms)
        self.timing = []   # [pre, inference, decode, callback] ms
        self.events = []
        self.node.create_subscription(Detection2DArray, '/detections', self.on_det, 50)
        self.node.create_subscription(Float64MultiArray, '/ppe_detector/timing',
                                      self.on_timing, 50)
        qos = QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.node.create_subscription(String, '/patrol/events', self.on_event, qos)
        self.ex = SingleThreadedExecutor()
        self.ex.add_node(self.node)
        self.thread = threading.Thread(target=self.ex.spin, daemon=True)
        self.thread.start()

    def on_det(self, msg):
        now = time.time()
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        with self.lock:
            if self.recording:
                self.det.append((now - stamp) * 1000.0)

    def on_timing(self, msg):
        with self.lock:
            if self.recording:
                self.timing.append(list(msg.data))

    def on_event(self, msg):
        with self.lock:
            if self.recording:
                self.events.append(json.loads(msg.data))

    def start(self):
        with self.lock:
            self.det, self.timing, self.events = [], [], []
            self.recording = True

    def stop(self):
        with self.lock:
            self.recording = False
            return list(self.det), list(self.timing), list(self.events)


def launch(cmd, log):
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGINT)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


def detector_scenario(col, threads, rate, window, log, reliability='reliable'):
    det_exe = os.path.join(INSTALL, 'ppe_detector', 'lib', 'ppe_detector', 'ppe_detector_node')
    pub_exe = os.path.join(INSTALL, 'ppe_bringup', 'lib', 'ppe_bringup', 'sample_image_publisher')
    det = launch([det_exe, '--ros-args', '-p', 'autostart:=true',
                  '-p', f'intra_op_threads:={threads}', '-p', 'publish_annotated:=false',
                  '-p', f'image_reliability:={reliability}'], log)
    time.sleep(4.0)
    pub = launch([pub_exe, '--ros-args', '-p', f'rate_hz:={rate}',
                  '-p', f'images:=[{SAMPLES}]'], log)
    time.sleep(5.0)  # warm-up
    col.start()
    c0, t0 = cpu_seconds(det.pid), time.time()
    time.sleep(window)
    c1, t1 = cpu_seconds(det.pid), time.time()
    lat, timing, _ = col.stop()
    stop(pub)
    stop(det)
    inf = [t[1] for t in timing]
    cb = [t[3] for t in timing]
    return {
        'intra_op_threads': 'default' if threads == 0 else threads,
        'offered_fps': rate,
        'image_reliability': reliability,
        'window_s': round(t1 - t0, 1),
        'frames_processed': len(lat),
        'throughput_fps': round(len(lat) / (t1 - t0), 2),
        'latency_ms_p50': pct(lat, 50),
        'latency_ms_p95': pct(lat, 95),
        'inference_ms_p50': pct(inf, 50),
        'inference_ms_p95': pct(inf, 95),
        'node_callback_ms_p50': pct(cb, 50),
        'node_callback_ms_p95': pct(cb, 95),
        'cpu_percent_of_one_core': round(100.0 * (c1 - c0) / (t1 - t0), 1),
    }


def e2e_scenario(col, window, log):
    cmd = ['ros2', 'launch', 'ppe_bringup', 'replay_demo.launch.py', 'images:=plant-cctv',
           'rate_hz:=5.0', 'cooldown_s:=1.0', 'start_delay_s:=3.0']
    proc = launch(cmd, log)
    time.sleep(3.0)
    col.start()
    time.sleep(window)
    _, _, events = col.stop()
    stop(proc)
    sent = [e for e in events if e['event'] == 'goal_sent']
    trig = [(e['wall'] - e['trigger_stamp']) * 1000.0 for e in sent]
    first = [(e['wall'] - e['first_stamp']) * 1000.0 for e in sent]
    return {
        'images': 'plant-cctv', 'offered_fps': 5.0, 'consecutive_frames': 3,
        'window_s': window,
        'goals_sent': len(sent),
        'goals_succeeded': sum(e['event'] == 'succeeded' for e in events),
        'trigger_frame_to_goal_ms_p50': pct(trig, 50),
        'trigger_frame_to_goal_ms_p95': pct(trig, 95),
        'first_frame_to_goal_ms_p50': pct(first, 50),
        'first_frame_to_goal_ms_p95': pct(first, 95),
        'action_server': 'fake NavigateToPose server (stand-in for Nav2)',
    }


def write_md(res, path):
    m = res['machine']
    lines = [
        '# Measurements', '',
        f"Measured by `scripts/measure.py` on {m['date_utc']} UTC. Raw values: "
        '`results/benchmark.json`.', '',
        '## Machine', '',
        f"- CPU: {m['cpu_model']}, {m['logical_cpus']} logical CPUs "
        f"({m['threads_per_core']} thread(s) per core), no GPU used",
        f"- RAM: {m['ram_gib']} GiB",
        f"- OS: {m['os']}, kernel {m['kernel']}",
        f"- ROS 2 {m['ros_distro']}, ONNX Runtime {m['onnxruntime']} (CPU execution provider)",
        '', '## Detector node', '',
        '| intra-op threads | image QoS | offered fps | processed fps | latency p50 ms '
        '| latency p95 ms | inference p50 ms | inference p95 ms | CPU % of one core |',
        '|---|---|---|---|---|---|---|---|---|',
    ]
    for d in res['detector']:
        lines.append(
            f"| {d['intra_op_threads']} | {d['image_reliability']} | {d['offered_fps']} | "
            f"{d['throughput_fps']} | "
            f"{d['latency_ms_p50']} | {d['latency_ms_p95']} | {d['inference_ms_p50']} | "
            f"{d['inference_ms_p95']} | {d['cpu_percent_of_one_core']} |")
    e = res['e2e']
    lines += [
        '', 'Latency: image header stamp to Detection2DArray received by the measuring script '
        '(two DDS hops, colour conversion, letterbox, inference, decode, NMS). '
        'At 50 offered fps the node is saturated and keeps only the newest frame, '
        'so processed fps is its throughput.', '',
        '## Detection to goal (replayed images, fake NavigateToPose server)', '',
        f"- goals sent in {e['window_s']} s: {e['goals_sent']} "
        f"(succeeded: {e['goals_succeeded']})",
        f"- frame that completed the run of {e['consecutive_frames']} to goal sent: "
        f"p50 {e['trigger_frame_to_goal_ms_p50']} ms, p95 {e['trigger_frame_to_goal_ms_p95']} ms",
        '- first frame of the run to goal sent (includes waiting for '
        f"{e['consecutive_frames']} frames at {e['offered_fps']} fps): "
        f"p50 {e['first_frame_to_goal_ms_p50']} ms, p95 {e['first_frame_to_goal_ms_p95']} ms",
        '',
    ]
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--window', type=float, default=30.0)
    a = ap.parse_args()
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    rclpy.init()
    col = Collector()
    res = {'machine': machine(), 'detector': []}
    with open(os.path.join(ROOT, 'results', 'measure.log'), 'w') as log:
        for threads in (1, 0):
            for rate in (50.0, 5.0):
                r = detector_scenario(col, threads, rate, a.window, log)
                print(json.dumps(r), flush=True)
                res['detector'].append(r)
        # The same 5 fps run with a best-effort subscription, to show why the
        # node defaults to reliable.
        r = detector_scenario(col, 0, 5.0, a.window, log, 'best_effort')
        print(json.dumps(r), flush=True)
        res['detector'].append(r)
        res['e2e'] = e2e_scenario(col, 2 * a.window, log)
        print(json.dumps(res['e2e']), flush=True)
    col.ex.shutdown()
    col.thread.join(timeout=5)
    rclpy.shutdown()
    with open(os.path.join(ROOT, 'results', 'benchmark.json'), 'w') as f:
        json.dump(res, f, indent=1)
    write_md(res, os.path.join(ROOT, 'results', 'benchmark.md'))


if __name__ == '__main__':
    main()
