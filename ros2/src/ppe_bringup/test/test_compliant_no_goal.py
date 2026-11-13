"""
A replayed image where the model finds only worn PPE must not send a goal.

site-backs: the model finds Vest x3 and Helmet x2 at threshold 0.25 and no
missing item, so after many frames the patrol node must still be idle.
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
from replay_helpers import include_replay, Watcher  # noqa: E402

FRAMES = 20


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    return launch.LaunchDescription([
        include_replay(images='site-backs', rate_hz=5.0, start_delay_s=3.0),
        launch_testing.actions.ReadyToTest(),
    ])


class TestCompliantNoGoal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.w = Watcher('compliant_watcher')

    @classmethod
    def tearDownClass(cls):
        cls.w.destroy()
        rclpy.shutdown()

    def test_no_goal_after_many_frames(self):
        ok = self.w.spin_until(lambda: len(self.w.detections) >= FRAMES, 60.0)
        self.assertTrue(ok, f'only {len(self.w.detections)} detection messages')
        # Let any goal that might be in flight show up.
        self.w.spin_until(lambda: False, 1.0)
        self.assertNotIn('goal_sent', self.w.event_names())
        labels = {d.results[0].hypothesis.class_id
                  for m in self.w.detections for d in m.detections}
        self.assertEqual(labels, {'Vest', 'Helmet'})
