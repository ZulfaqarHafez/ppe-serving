"""
Save frames from a sensor_msgs/Image topic as PNG files.

python3 scripts/save_frames.py --topic /detections/image --out docs/evidence/frames \
    --count 5 --every 2.0 [--sim-time]
Saves one frame every --every seconds (wall clock), --count frames, then exits.
Needs rclpy, numpy and OpenCV (python3-opencv).
"""
import argparse
import os
import time

import cv2
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--topic', default='/detections/image')
    ap.add_argument('--out', required=True)
    ap.add_argument('--prefix', default='frame')
    ap.add_argument('--count', type=int, default=5)
    ap.add_argument('--every', type=float, default=1.0)
    ap.add_argument('--timeout', type=float, default=120.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rclpy.init()
    node = rclpy.create_node('save_frames')
    state = {'saved': 0, 'last': 0.0}

    def on_image(msg):
        now = time.time()
        if state['saved'] >= a.count or now - state['last'] < a.every:
            return
        ch = 3 if msg.encoding in ('rgb8', 'bgr8') else 1
        img = np.frombuffer(bytes(msg.data), np.uint8).reshape(msg.height, msg.step)
        img = img[:, :msg.width * ch].reshape(msg.height, msg.width, ch)
        if msg.encoding == 'rgb8':
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        path = os.path.join(a.out, f"{a.prefix}_{state['saved']:02d}.png")
        cv2.imwrite(path, img)
        print(path, msg.header.frame_id, flush=True)
        state['saved'] += 1
        state['last'] = now

    node.create_subscription(Image, a.topic, on_image, qos_profile_sensor_data)
    end = time.time() + a.timeout
    while rclpy.ok() and state['saved'] < a.count and time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
