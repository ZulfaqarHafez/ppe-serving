"""
A replayed image with a missing helmet must lead to a NavigateToPose goal.

Brings up the replay publisher (plant-cctv, where the model finds No-Helmet at
0.627), the detector, the patrol node and the fake NavigateToPose server, and
checks that the patrol node sends a goal after 3 frames and sees it succeed.
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


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description():
    return launch.LaunchDescription([
        include_replay(images='plant-cctv', rate_hz=5.0, start_delay_s=3.0),
        launch_testing.actions.ReadyToTest(),
    ])


class TestViolationSendsGoal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.w = Watcher('violation_watcher')

    @classmethod
    def tearDownClass(cls):
        cls.w.destroy()
        rclpy.shutdown()

    def test_goal_sent_and_succeeds(self):
        ok = self.w.spin_until(lambda: 'succeeded' in self.w.event_names(), 60.0)
        self.assertTrue(ok, f'events so far: {self.w.event_names()}')
        sent = [e for e in self.w.events if e['event'] == 'goal_sent']
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['label'], 'No-Helmet')
        self.assertGreaterEqual(sent[0]['score'], 0.5)
        self.assertEqual(sent[0]['frames'], 3)
        self.assertEqual(sent[0]['trigger_frame'], 'plant-cctv')
        names = self.w.event_names()
        self.assertLess(names.index('goal_sent'), names.index('goal_accepted'))
        self.assertIn('feedback', names)
