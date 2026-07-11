"""时间轴单帧键盘/滚轮交互测试。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from timeline_track import TimelineTrack


class TestTimelineWheelInteraction(unittest.TestCase):
    def make_track(self):
        track = TimelineTrack.__new__(TimelineTrack)
        track.app = MagicMock()
        return track

    def test_wheel_up_moves_track_backward_ten_frames(self):
        track = self.make_track()
        event = SimpleNamespace(delta=120, num=None)

        result = track._on_mouse_wheel(event)

        track.app._move_timeline_by_frames.assert_called_once_with(-10, track=track)
        self.assertEqual(result, "break")

    def test_wheel_down_moves_track_forward_ten_frames(self):
        track = self.make_track()
        event = SimpleNamespace(delta=-120, num=None)

        result = track._on_mouse_wheel(event)

        track.app._move_timeline_by_frames.assert_called_once_with(10, track=track)
        self.assertEqual(result, "break")


if __name__ == "__main__":
    unittest.main()
