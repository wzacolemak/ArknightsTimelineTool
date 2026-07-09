"""pause_engine 单元测试（无需游戏 / tkinter）。"""
import unittest

from pause_engine import PauseEngine, is_replay_mode, normalize_track


class TestPauseEngine(unittest.TestCase):
    def test_is_replay_mode(self):
        self.assertTrue(is_replay_mode("对轴模式"))
        self.assertTrue(is_replay_mode("replay"))
        self.assertFalse(is_replay_mode("打轴模式"))
        self.assertFalse(is_replay_mode("chart"))

    def test_cross_node_fires_once(self):
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "pause_enabled": True,
                "nodes": [
                    {"frame": 60, "name": "op", "pause_on_arrive": True},
                ],
            }
        ]
        self.assertEqual(eng.tick(50, tracks), [])
        events = eng.tick(61, tracks)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame"], 60)
        # 再 tick 不重复
        self.assertEqual(eng.tick(70, tracks), [])

    def test_chart_mode_ignored(self):
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "打轴模式",
                "nodes": [{"frame": 10, "name": "x"}],
            }
        ]
        eng.tick(0, tracks)
        self.assertEqual(eng.tick(20, tracks), [])

    def test_pause_flags(self):
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "pause_enabled": False,
                "nodes": [{"frame": 10, "name": "x"}],
            }
        ]
        eng.tick(0, tracks)
        self.assertEqual(eng.tick(20, tracks), [])

        eng2 = PauseEngine()
        tracks2 = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "nodes": [{"frame": 10, "name": "x", "pause_on_arrive": False}],
            }
        ]
        eng2.tick(0, tracks2)
        self.assertEqual(eng2.tick(20, tracks2), [])

    def test_auto_reset_clears_dedup(self):
        eng = PauseEngine(reset_threshold=30)
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "nodes": [{"frame": 60, "name": "op"}],
            }
        ]
        eng.tick(50, tracks)
        self.assertEqual(len(eng.tick(61, tracks)), 1)
        # 回退到 0
        self.assertEqual(eng.tick(0, tracks), [])
        # 再次跨越可触发
        self.assertEqual(len(eng.tick(61, tracks)), 1)

    def test_not_running_skips(self):
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "nodes": [{"frame": 10, "name": "x"}],
            }
        ]
        eng.tick(0, tracks, is_running=True)
        self.assertEqual(eng.tick(20, tracks, is_running=False), [])

    def test_normalize_defaults(self):
        t = normalize_track({"name": "a", "nodes": [{"frame": 1, "name": "n"}]})
        self.assertTrue(t["pause_enabled"])
        self.assertTrue(t["nodes"][0]["pause_on_arrive"])


if __name__ == "__main__":
    unittest.main()
