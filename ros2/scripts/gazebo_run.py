"""
Run the Gazebo + Nav2 demo once, headless, and keep the evidence.

    python3 scripts/gazebo_run.py [--timeout 240]

Starts `ros2 launch ppe_bringup gazebo_demo.launch.py`, records a small rosbag2
(no images), saves annotated detector frames as PNG every 2 s of wall time,
samples Gazebo's real-time factor from /world/default/stats, waits for the
patrol node's goal to finish, dumps the ROS graph, then shuts everything down.

Outputs
  docs/evidence/gazebo/run.log            launch output (colour codes removed)
  docs/evidence/gazebo/rosbag/            rosbag2 (mcap)
  docs/evidence/gazebo/frames/*.png       annotated camera frames
  docs/evidence/graph/                    node/topic/action lists, node_graph.dot/.svg
  results/gazebo_run.json
Exits non-zero if no goal succeeded.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Float64MultiArray, String
from vision_msgs.msg import Detection2DArray

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVID = os.path.join(ROOT, 'docs', 'evidence')
OURS = ['/ppe_detector', '/ppe_patrol', '/camera_bridge', '/bt_navigator',
        '/controller_server', '/planner_server', '/amcl']
BAG_TOPICS = ['/detections', '/patrol/events', '/ppe_detector/timing', '/odom', '/plan',
              '/amcl_pose', '/navigate_to_pose/_action/status',
              '/navigate_to_pose/_action/feedback']


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


class Watch:
    def __init__(self, frames_dir):
        self.node = rclpy.create_node('gazebo_run_watch')
        self.frames_dir = frames_dir
        self.events, self.timing, self.det = [], [], []
        self.saved, self.last_save = 0, 0.0
        self.lock = threading.Lock()
        qos = QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.node.create_subscription(String, '/patrol/events', self.on_event, qos)
        self.node.create_subscription(Float64MultiArray, '/ppe_detector/timing',
                                      lambda m: self.timing.append(list(m.data)), 50)
        self.node.create_subscription(Detection2DArray, '/detections', self.on_det, 50)
        self.node.create_subscription(Image, '/detections/image', self.on_image,
                                      qos_profile_sensor_data)
        self.ex = SingleThreadedExecutor()
        self.ex.add_node(self.node)
        self.thread = threading.Thread(target=self.ex.spin, daemon=True)
        self.thread.start()

    def on_event(self, msg):
        e = json.loads(msg.data)
        print('event:', msg.data, flush=True)
        with self.lock:
            self.events.append(e)

    def on_det(self, msg):
        best = {}
        for d in msg.detections:
            h = d.results[0].hypothesis
            best[h.class_id] = max(best.get(h.class_id, 0.0), h.score)
        with self.lock:
            self.det.append((time.time(), best))

    def on_image(self, msg):
        now = time.time()
        if now - self.last_save < 1.5 or self.saved >= 12:
            return
        img = np.frombuffer(bytes(msg.data), np.uint8).reshape(msg.height, msg.step)
        img = img[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
        path = os.path.join(self.frames_dir, f'frame_{self.saved:02d}.png')
        cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        self.saved += 1
        self.last_save = now

    def names(self):
        with self.lock:
            return [e['event'] for e in self.events]


def _stamps(txt, key):
    out = []
    for m in re.finditer(key + r'\s*\{\s*(?:sec:\s*(\d+))?\s*(?:nsec:\s*(\d+))?\s*\}', txt):
        out.append(int(m.group(1) or 0) + int(m.group(2) or 0) * 1e-9)
    return out


def sample_rtf(seconds, out):
    """
    Real-time factor from Gazebo's world stats over `seconds`.

    Returns simulated seconds divided by real seconds between the first and the
    last stats message (both clocks come from Gazebo).
    """
    try:
        txt = subprocess.run(['gz', 'topic', '-e', '-t', '/world/default/stats', '-d',
                              str(seconds)], capture_output=True, text=True,
                             timeout=seconds + 15).stdout
    except subprocess.TimeoutExpired as e:
        txt = (e.stdout or b'').decode() if isinstance(e.stdout, bytes) else (e.stdout or '')
    sim, real = _stamps(txt, 'sim_time'), _stamps(txt, 'real_time')
    n = min(len(sim), len(real))
    if n >= 2 and real[n - 1] > real[0]:
        out.update({'sim_s': round(sim[n - 1] - sim[0], 3),
                    'real_s': round(real[n - 1] - real[0], 3),
                    'rtf': round((sim[n - 1] - sim[0]) / (real[n - 1] - real[0]), 3)})


def node_info(name):
    return subprocess.run(['ros2', 'node', 'info', name], capture_output=True, text=True,
                          timeout=30).stdout


def dump_graph(gdir):
    os.makedirs(gdir, exist_ok=True)

    def run(args):
        return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout

    with open(os.path.join(gdir, 'ros2_node_list.txt'), 'w') as f:
        f.write(run(['ros2', 'node', 'list']))
    with open(os.path.join(gdir, 'ros2_topic_list.txt'), 'w') as f:
        f.write(run(['ros2', 'topic', 'list', '-t']))
    with open(os.path.join(gdir, 'ros2_action_list.txt'), 'w') as f:
        f.write(run(['ros2', 'action', 'list', '-t']))
    edges, infos = [], {}
    for n in OURS:
        info = node_info(n)
        infos[n] = info
        section = None
        for line in info.splitlines():
            s = line.strip()
            if s.endswith(':') and not s.startswith('/'):
                section = s[:-1]
                continue
            if not s.startswith('/') or ':' not in s:
                continue
            name, typ = [x.strip() for x in s.split(':', 1)]
            if name in ('/rosout', '/parameter_events', '/clock', '/bond', '/tf_static') or \
                    name.startswith('/' + n.strip('/')):
                continue
            edges.append((n, section, name, typ))
    with open(os.path.join(gdir, 'ros2_node_info.txt'), 'w') as f:
        for n, info in infos.items():
            f.write(f'$ ros2 node info {n}\n{info}\n')
    # Keep topics and actions that connect two of the nodes above, plus the
    # camera input and the detector outputs.
    keep = {'/camera/image_raw', '/detections', '/detections/image', '/patrol/events',
            '/navigate_to_pose'}
    count = {}
    for n, sec, name, _ in edges:
        count.setdefault(name, set()).add(n)
    keep |= {k for k, v in count.items() if len(v) >= 2}
    lines = ['digraph ppe {', '  rankdir=LR; node [fontname="Helvetica", fontsize=11];']
    for n in OURS:
        lines.append(f'  "{n}" [shape=box, style="rounded,filled", fillcolor="#dbe8f6"];')
    seen = set()
    for n, sec, name, typ in edges:
        if name not in keep:
            continue
        if name not in seen:
            shape = 'hexagon' if 'Action' in sec else 'ellipse'
            lines.append(f'  "{name}" [shape={shape}, label="{name}\\n{typ}", fontsize=9];')
            seen.add(name)
        if sec in ('Publishers', 'Action Servers'):
            lines.append(f'  "{n}" -> "{name}";')
        elif sec in ('Subscribers', 'Action Clients'):
            lines.append(f'  "{name}" -> "{n}";')
    lines.append('  "gz sim (headless)" [shape=box, style="rounded,dashed"];')
    lines.append('  "gz sim (headless)" -> "/camera_bridge" [label="gz.msgs.Image"];')
    lines.append('}')
    dot = os.path.join(gdir, 'node_graph.dot')
    with open(dot, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    subprocess.run(['dot', '-Tsvg', dot, '-o', os.path.join(gdir, 'node_graph.svg')])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeout', type=float, default=240.0)
    a = ap.parse_args()
    gz_dir = os.path.join(EVID, 'gazebo')
    frames = os.path.join(gz_dir, 'frames')
    bag = os.path.join(gz_dir, 'rosbag')
    for p in (frames, bag):
        shutil.rmtree(p, ignore_errors=True)
    os.makedirs(frames)
    rclpy.init()
    w = Watch(frames)
    raw_log = os.path.join(gz_dir, 'run.raw.log')
    t_start = time.time()
    with open(raw_log, 'w') as log:
        launch = subprocess.Popen(['ros2', 'launch', 'ppe_bringup', 'gazebo_demo.launch.py'],
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        rec = subprocess.Popen(['ros2', 'bag', 'record', '-s', 'mcap', '-o', bag,
                                '--include-hidden-topics', '--topics'] + BAG_TOPICS,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        rtf = {}
        rtf_thread = None
        ok = False
        while time.time() - t_start < a.timeout:
            time.sleep(1.0)
            names = w.names()
            if rtf_thread is None and 'goal_accepted' in names:
                # Sample the real-time factor while Nav2 drives the robot.
                rtf_thread = threading.Thread(target=sample_rtf, args=(20, rtf))
                rtf_thread.start()
            if any(n in names for n in ('succeeded', 'aborted', 'canceled')):
                ok = 'succeeded' in names
                break
        t_done = time.time()
        if rtf_thread:
            rtf_thread.join()
        idle_rtf = {}
        sample_rtf(10, idle_rtf)
        dump_graph(os.path.join(EVID, 'graph'))
        for p in (rec, launch):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGINT)
        for p in (rec, launch):
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
    subprocess.run('pkill -f "gz sim"', shell=True)
    w.ex.shutdown()
    rclpy.shutdown()

    with open(raw_log) as f:
        text = re.sub(r'\x1b\[[0-9;]*m', '', f.read())
    with open(os.path.join(gz_dir, 'run.log'), 'w') as f:
        f.write(text)
    os.remove(raw_log)

    ev = w.events
    sent = [e for e in ev if e['event'] == 'goal_sent']
    acc = [e for e in ev if e['event'] == 'goal_accepted']
    done = [e for e in ev if e['event'] in ('succeeded', 'aborted', 'canceled')]
    inf = [t[1] for t in w.timing]
    det_times = [t for t, _ in w.det]
    scores = {}
    for _, best in w.det:
        for k, v in best.items():
            scores.setdefault(k, []).append(v)
    res = {
        'what': 'One headless run of gazebo_demo.launch.py: Gazebo Harmonic, TurtleBot3 '
                'Waffle with an RGB camera, Nav2 (AMCL, tb3_sandbox map), the detector on '
                'the simulated camera (5 Hz) and the patrol node sending a real '
                'NavigateToPose goal.',
        'goal_result': done[-1]['event'] if done else None,
        'goals_sent': len(sent),
        'goal_events': [e['event'] for e in ev if e['event'] != 'feedback'],
        'wall_s_launch_to_result': round(t_done - t_start, 1),
        'accepted_goal': None,
        'real_time_factor_note': 'sim seconds / real seconds from /world/default/stats; '
                                 'first window starts when the goal is accepted (20 s), '
                                 'second after the result (10 s)',
        'real_time_factor_while_driving': rtf,
        'real_time_factor_after_goal': idle_rtf,
        'detector_in_sim': {
            'frames': len(det_times),
            'fps_wall': round((len(det_times) - 1) / (det_times[-1] - det_times[0]), 2)
            if len(det_times) > 1 else None,
            'inference_ms_p50': pct(inf, 50), 'inference_ms_p95': pct(inf, 95),
            'max_score_by_class': {k: round(max(v), 3) for k, v in scores.items()},
            'median_score_by_class': {k: pct(v, 50) for k, v in scores.items()},
        },
        'frames_saved': w.saved,
    }
    if acc and sent:
        s = [e for e in sent if e['t'] <= acc[-1]['t']][-1]
        res['accepted_goal'] = {
            'label': s['label'], 'score': s['score'], 'frames': s['frames'],
            'sim_s_trigger_image_to_goal_sent': round(s['t'] - s['trigger_stamp'], 3),
            'sim_s_goal_sent_to_result': round(done[-1]['t'] - s['t'], 3) if done else None,
            'wall_s_goal_sent_to_result': round(done[-1]['wall'] - s['wall'], 3) if done else None,
        }
    # A short clip of the saved frames (1.5 s of wall time apart, shown at 2 fps).
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', '2', '-i',
                    os.path.join(frames, 'frame_%02d.png'), '-c:v', 'libx264', '-pix_fmt',
                    'yuv420p', '-crf', '28', os.path.join(gz_dir, 'camera_clip.mp4')])
    with open(os.path.join(ROOT, 'results', 'gazebo_run.json'), 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
