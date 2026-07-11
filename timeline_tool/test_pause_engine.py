"""pause_engine 单元测试（无需游戏 / tkinter）。"""
import unittest

import config
from pause_engine import (
    PauseEngine,
    is_replay_mode,
    normalize_track,
    resolve_lead_frames,
)
from utils import format_frame_time


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
        self.assertEqual(events[0]["trigger_frame"], 60)
        # 再 tick 不重复
        self.assertEqual(eng.tick(70, tracks), [])

    def test_lead_frames_triggers_early(self):
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "nodes": [{"frame": 60, "name": "op"}],
            }
        ]
        eng.tick(50, tracks, lead_frames=2)
        # 节点 60、lead=2 → 在跨越 58 时触发
        events = eng.tick(58, tracks, lead_frames=2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame"], 60)
        self.assertEqual(events[0]["trigger_frame"], 58)
        self.assertEqual(events[0]["lead_frames"], 2)
        # 到点不再重复
        self.assertEqual(eng.tick(61, tracks, lead_frames=2), [])

    def test_lead_frames_can_trigger_a_node_at_the_start(self):
        """节点 frame=1、提前 1 帧时应在初始 frame=0 触发，不能永久漏掉。"""
        eng = PauseEngine()
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "nodes": [{"frame": 1, "name": "opening"}],
            }
        ]

        events = eng.tick(0, tracks, lead_frames=1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame"], 1)
        self.assertEqual(events[0]["trigger_frame"], 0)

    def test_resolve_lead_frames(self):
        self.assertEqual(resolve_lead_frames(lead_frames=2, lead_ms=999, logic_fps=30), 2)
        self.assertEqual(resolve_lead_frames(lead_frames=None, lead_ms=30, logic_fps=30), 1)
        self.assertEqual(resolve_lead_frames(lead_frames=None, lead_ms=0, logic_fps=30), 0)
        self.assertEqual(resolve_lead_frames(lead_frames=None, lead_ms=100, logic_fps=30), 3)
        self.assertEqual(resolve_lead_frames(lead_frames=-1), 0)

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

    def test_120_frame_cost_cycle_still_uses_global_30hz_frames(self):
        """回归：120f 表示一个费用回复周期 = 120 个 30Hz 逻辑帧 = 4 秒，
        不是 120 FPS 时间轴。"""
        eng = PauseEngine()
        tracks = [
            {
                "name": "contract",
                "mode": "对轴模式",
                "nodes": [{"frame": 120, "name": "four-seconds"}],
            }
        ]
        eng.tick(119, tracks)
        events = eng.tick(120, tracks)
        self.assertEqual(events[0]["frame"], 120)
        self.assertEqual(120 // 30, 4)

    def test_120f_formats_as_four_seconds(self):
        """120f 在费用尺/时间轴的 30Hz 显示下等于 00:04:00。"""
        self.assertEqual(format_frame_time(120), "00:04:00")

    def test_logic_fps_must_not_be_120(self):
        """门闸：禁止把 config.FPS / LOGIC_FPS 改成 120。"""
        self.assertEqual(config.FPS, 30)
        self.assertEqual(config.LOGIC_FPS, config.FPS)
        self.assertNotEqual(config.FPS, 120)
        self.assertNotEqual(config.LOGIC_FPS, 120)

    def test_keyboard_scroll_step_is_one_logical_frame(self):
        """左右键用于细调，每次只移动一个逻辑帧。"""
        self.assertEqual(config.KEYBOARD_SCROLL_STEP, 1)

    def test_mouse_wheel_scroll_step_is_ten_logical_frames(self):
        """轨道滚轮用于粗调，每格移动十个逻辑帧。"""
        self.assertEqual(config.MOUSE_WHEEL_SCROLL_STEP, 10)

    def test_old_pause_symbols_absent(self):
        """清除：旧暂停通道/冷却/多通道配置符号不得残留。"""
        for name in ("PAUSE_HOTKEY", "PAUSE_COOLDOWN_SEC", "PAUSE_PC_METHODS", "ADB_ALSO_FOR_CLIENT"):
            self.assertFalse(hasattr(config, name), f"config 仍含旧符号 {name}")


if __name__ == "__main__":
    unittest.main()
