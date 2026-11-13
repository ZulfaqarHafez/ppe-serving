"""
Parity through ROS: detector node output on the five samples vs samples.json.

Same labels at thresholds 0.25 and 0.5, each score within 0.001 (samples.json
rounds scores to 3 decimals).
"""
import os
import sys
import unittest

import launch
import launch_testing.actions
import launch_testing.markers
import pytest
import rclpy

sys.path.insert(0, os.path.dirname(__file__))
from replay_helpers import include_replay, load_samples, Watcher  # noqa: E402

TOLERANCE = 0.001


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    return launch.LaunchDescription([
        include_replay(images='site-backs,rooftop-cctv,plant-cctv,hi-vis-walk,packing-cctv',
                       rate_hz=2.0, start_delay_s=3.0),
        launch_testing.actions.ReadyToTest(),
    ])


def compare(expected, found):
    """Pair detections by label and closest score; return (error or '', worst diff)."""
    if len(expected) != len(found):
        return f'expected {len(expected)} detections, found {len(found)}', 0.0
    pool = list(found)
    worst = 0.0
    for e in expected:
        same = [f for f in pool if f[0] == e['label']]
        if not same:
            return f'no {e["label"]}', worst
        best = min(same, key=lambda f: abs(f[1] - e['score']))
        pool.remove(best)
        worst = max(worst, abs(best[1] - e['score']))
    return ('' if worst <= TOLERANCE else f'worst score difference {worst:.4f}'), worst


class TestNodeParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.w = Watcher('parity_watcher')

    @classmethod
    def tearDownClass(cls):
        cls.w.destroy()
        rclpy.shutdown()

    def test_matches_samples_json(self):
        samples = load_samples()
        first = {}

        def collected():
            for m in self.w.detections:
                first.setdefault(m.header.frame_id, m)
            return set(samples) <= set(first)

        self.assertTrue(self.w.spin_until(collected, 60.0), f'got {sorted(first)}')
        worst = 0.0
        for sid, s in samples.items():
            found = [(d.results[0].hypothesis.class_id, d.results[0].hypothesis.score)
                     for d in first[sid].detections]
            for thr in ('0.25', '0.5'):
                kept = [f for f in found if f[1] >= float(thr)]
                err, w = compare(s['at'][thr]['detections'], kept)
                worst = max(worst, w)
                self.assertEqual(err, '', f'{sid} at {thr}')
        print(f'node parity: worst score difference {worst:.4f}')
