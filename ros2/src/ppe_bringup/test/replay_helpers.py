"""Shared pieces of the replay launch tests."""
import json
import os
import time

from ament_index_python.packages import get_package_share_directory
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray


def include_replay(**launch_args):
    path = os.path.join(get_package_share_directory('ppe_bringup'), 'launch',
                        'replay_demo.launch.py')
    args = {k: str(v) for k, v in launch_args.items()}
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(path),
                                    launch_arguments=args.items())


def load_samples():
    path = os.path.join(get_package_share_directory('ppe_bringup'), 'samples', 'samples.json')
    with open(path) as f:
        return {s['id']: s for s in json.load(f)['samples']}


class Watcher:
    """Collects detections and patrol events in a test process."""

    def __init__(self, name):
        self.node = rclpy.create_node(name)
        self.detections = []
        self.events = []
        self.node.create_subscription(Detection2DArray, 'detections', self.detections.append, 50)
        qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.node.create_subscription(
            String, 'patrol/events', lambda m: self.events.append(json.loads(m.data)), qos)

    def spin_until(self, done, timeout):
        end = time.time() + timeout
        while time.time() < end:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if done():
                return True
        return False

    def event_names(self):
        return [e['event'] for e in self.events]

    def destroy(self):
        self.node.destroy_node()
