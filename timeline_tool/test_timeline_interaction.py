"""时间轴单帧键盘/滚轮交互测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import config
from timeline_track import TimelineTrack


class TestTimelineWheelInteraction(unittest.TestCase):
    def make_track(self):
        track = TimelineTrack.__new__(TimelineTrack)
        track.app = MagicMock()
        return track

    def test_wheel_up_moves_track_backward_one_frame(self):
        track = self.make_track()
        event = SimpleNamespace(delta=120, num=None)

        result = track._on_mouse_wheel(event)

        track.app._move_timeline_by_frames.assert_called_once_with(-1, track=track)
        self.assertEqual(result, "break")

    def test_wheel_down_moves_track_forward_one_frame(self):
        track = self.make_track()
        event = SimpleNamespace(delta=-120, num=None)

        result = track._on_mouse_wheel(event)

        track.app._move_timeline_by_frames.assert_called_once_with(1, track=track)
        self.assertEqual(result, "break")

    def test_node_interaction_tolerances(self):
        self.assertEqual(config.NODE_FIND_TOLERANCE, 3)
        self.assertEqual(config.NODE_CLICK_TOLERANCE, 3)

    def test_node_selection_keeps_three_frame_range(self):
        track = self.make_track()
        node = {"frame": 100, "name": "A"}
        track.timeline_data = [node]

        self.assertIs(track._find_node_at(100), node)
        self.assertIs(track._find_node_at(97), node)
        self.assertIs(track._find_node_at(103), node)
        self.assertIsNone(track._find_node_at(96))
        self.assertIsNone(track._find_node_at(104))


if __name__ == "__main__":
    unittest.main()
