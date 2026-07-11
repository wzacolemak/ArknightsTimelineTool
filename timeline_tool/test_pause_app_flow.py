"""顺序暂停状态机集成测试（Task 3）。

用 TimelineApp.__new__(TimelineApp) 构造无 Tk 实例，手工注入所需属性与 mock，
覆盖 brief 要求的 9 条用例。不启动真实 WebSocket / Win32 发键。
"""
import os
import sys
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from tkinter import ttk
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeStringVar:
    """轻量 tk.StringVar 替身：get 返回合法整数字符串，供真实 _get_pause_lead_frames 读取。"""

    def __init__(self, value="0"):
        self._v = str(value)

    def get(self):
        return self._v

    def set(self, value):
        self._v = str(value)

    def trace_add(self, *_args, **_kwargs):
        pass

    def trace_remove(self, *_args, **_kwargs):
        pass


class _FakeWidget:
    def __init__(self, class_name, master=None, *, drag_zone=False):
        self._class_name = class_name
        self.master = master
        self._hud_drag_zone = drag_zone

    def winfo_class(self):
        return self._class_name


def make_app():
    """构造一个无 Tk 的 TimelineApp 实例，仅装配暂停状态机需要的属性。"""
    from app import TimelineApp
    from pause_queue import PendingPauseQueue
    from pause_engine import PauseEngine

    app = TimelineApp.__new__(TimelineApp)
    app.pause_engine = PauseEngine()
    app._pending_pause_groups = PendingPauseQueue()
    app._active_pause_group = None
    app._pause_gate = None
    app._pause_gate_frame = -1
    app._pause_verify = None
    app._pause_status = ""
    app._admin_warned = False
    app._is_admin = True
    app.current_game_frame = 0
    app.tracks = []
    app._bound_window = None
    # 真实 _get_pause_lead_frames 会读 pause_lead_var.get()；返回 "0" → lead=0
    app.pause_lead_var = _FakeStringVar("0")
    # _last_pause_send_ts 必须已删除；存在即失败
    return app


def make_event(track_idx, frame, trigger_frame, name, track_name=None, lead=0):
    return {
        "track_idx": track_idx,
        "frame": frame,
        "trigger_frame": trigger_frame,
        "lead_frames": lead,
        "name": name,
        "track_name": track_name or f"轨道{track_idx}",
    }


class TestPauseAppFlow(unittest.TestCase):
    # ------------------------------------------------------------------
    # 用例 1：gate=frozen 时 _queue_pause_events 仍入队
    # ------------------------------------------------------------------
    def test_queue_pause_events_enqueues_even_when_gate_frozen(self):
        app = make_app()
        app._pause_gate = "frozen"
        ev = make_event(0, 60, 59, "A")
        app._queue_pause_events([ev])
        self.assertEqual(len(app._pending_pause_groups), 1)
        top = app._pending_pause_groups.peek()
        self.assertEqual(top.trigger_frame, 59)

    # ------------------------------------------------------------------
    # 用例 2：gate=None 时派发 PC ESC、pop 一个组、进入 verifying、active 为该组
    # ------------------------------------------------------------------
    def test_dispatch_sends_pc_esc_and_enters_verifying(self):
        app = make_app()
        ev = make_event(0, 60, 59, "A")
        app._queue_pause_events([ev])
        group = app._pending_pause_groups.peek()

        win = {"hwnd": 12345, "title": "明日方舟", "class_name": "UnityWndClass"}
        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", return_value="SendInput(Escape)") as mock_pc, \
             patch("app.looks_like_emulator_window", return_value=False):
            ok = app._dispatch_next_pause_group(current_frame=59)

        self.assertTrue(ok)
        mock_pc.assert_called_once()
        # hold_ms 来自 config.PC_PAUSE_KEY_HOLD_MS；before/after 为置前回调
        kwargs = mock_pc.call_args.kwargs
        self.assertEqual(mock_pc.call_args.args[0], 12345)
        self.assertEqual(kwargs["hold_ms"], __import__("config").PC_PAUSE_KEY_HOLD_MS)
        self.assertEqual(app._pause_gate, "verifying")
        self.assertIs(app._active_pause_group, group)
        # 队列已 pop
        self.assertEqual(len(app._pending_pause_groups), 0)

    # ------------------------------------------------------------------
    # 用例 3：两个不同 trigger frame 的顺序派发
    # ------------------------------------------------------------------
    def test_two_distinct_triggers_dispatch_sequentially(self):
        app = make_app()
        ev1 = make_event(0, 60, 59, "A")
        ev2 = make_event(0, 80, 79, "B")
        app._queue_pause_events([ev1, ev2])
        win = {"hwnd": 1, "title": "明日方舟", "class_name": "UnityWndClass"}

        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", return_value="SendInput(Escape)") as mock_pc, \
             patch("app.looks_like_emulator_window", return_value=False):
            # 第一次派发：消费 ev1
            ok1 = app._dispatch_next_pause_group(current_frame=59)
            self.assertTrue(ok1)
            self.assertEqual(mock_pc.call_count, 1)
            self.assertEqual(app._active_pause_group.trigger_frame, 59)
            self.assertEqual(len(app._pending_pause_groups), 1)

            # gate=verifying 时第二次不得发送
            self.assertEqual(app._pause_gate, "verifying")
            ok2 = app._dispatch_next_pause_group(current_frame=59)
            self.assertFalse(ok2)
            self.assertEqual(mock_pc.call_count, 1)
            self.assertEqual(len(app._pending_pause_groups), 1)

            # 模拟用户恢复：frozen 且帧前进 → gate 释放
            app._pause_gate = "frozen"
            app._pause_gate_frame = 59
            app._update_pause_gate(79)
            self.assertIsNone(app._pause_gate)

            # 再派发第二个
            ok3 = app._dispatch_next_pause_group(current_frame=79)
            self.assertTrue(ok3)
            self.assertEqual(mock_pc.call_count, 2)
            self.assertEqual(app._active_pause_group.trigger_frame, 79)
            self.assertEqual(len(app._pending_pause_groups), 0)

    # ------------------------------------------------------------------
    # 用例 4：同 trigger frame 多轨节点只调用一次 send_pc_pause_key
    # ------------------------------------------------------------------
    def test_same_trigger_frame_multi_track_sends_once(self):
        app = make_app()
        ev_a = make_event(0, 60, 59, "A", track_name="T0")
        ev_b = make_event(1, 61, 59, "B", track_name="T1")
        # 合并到同一 trigger_frame 的组
        app._queue_pause_events([ev_a, ev_b])
        self.assertEqual(len(app._pending_pause_groups), 1)
        group = app._pending_pause_groups.peek()
        self.assertEqual(len(group.events), 2)

        win = {"hwnd": 1, "title": "明日方舟", "class_name": "UnityWndClass"}
        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", return_value="SendInput(Escape)") as mock_pc, \
             patch("app.looks_like_emulator_window", return_value=False):
            ok = app._dispatch_next_pause_group(current_frame=59)

        self.assertTrue(ok)
        mock_pc.assert_called_once()
        self.assertEqual(app._pause_gate, "verifying")

    # ------------------------------------------------------------------
    # 用例 5：Send API 异常：当前组被丢弃、gate 仍 None、不调用其他输入方法
    # ------------------------------------------------------------------
    def test_send_exception_drops_current_group_and_keeps_gate_none(self):
        app = make_app()
        ev1 = make_event(0, 60, 59, "A")
        ev2 = make_event(0, 80, 79, "B")
        app._queue_pause_events([ev1, ev2])
        win = {"hwnd": 1, "title": "明日方舟", "class_name": "UnityWndClass"}

        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", side_effect=OSError("boom")) as mock_pc, \
             patch("app.send_adb_pause_key") as mock_adb, \
             patch("app.looks_like_emulator_window", return_value=False):
            ok = app._dispatch_next_pause_group(current_frame=59)

        self.assertFalse(ok)
        # 当前组（队首 ev1）被 pop 丢弃
        self.assertIsNone(app._active_pause_group)
        self.assertIsNone(app._pause_gate)
        # 只尝试一次 PC，不调 ADB 或其他
        mock_pc.assert_called_once()
        mock_adb.assert_not_called()
        # 第二个组保留
        self.assertEqual(len(app._pending_pause_groups), 1)
        self.assertEqual(app._pending_pause_groups.peek().trigger_frame, 79)

    # ------------------------------------------------------------------
    # 用例 6：无窗口：组保留在队列
    # ------------------------------------------------------------------
    def test_no_window_keeps_group_in_queue(self):
        app = make_app()
        ev = make_event(0, 60, 59, "A")
        app._queue_pause_events([ev])
        with patch.object(app, "_resolve_live_game_window", return_value=None), \
             patch("app.send_pc_pause_key") as mock_pc:
            ok = app._dispatch_next_pause_group(current_frame=59)
        self.assertFalse(ok)
        mock_pc.assert_not_called()
        self.assertEqual(len(app._pending_pause_groups), 1)
        self.assertIsNone(app._pause_gate)

    # ------------------------------------------------------------------
    # 用例 7：_maybe_auto_pause 在 gate 非空时仍把 PauseEngine 事件入队
    # ------------------------------------------------------------------
    def test_maybe_auto_pause_enqueues_even_when_gate_non_empty(self):
        app = make_app()
        # 用 frozen 且未恢复，保证 _update_pause_gate 不会把 gate 清成 None
        app._pause_gate = "frozen"
        app._pause_gate_frame = 100
        app._active_pause_group = MagicMock(name="active")
        # 让 pause_engine.tick 返回一个事件
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "pause_enabled": True,
                "nodes": [{"frame": 100, "name": "n"}],
            }
        ]
        app.tracks = tracks
        # 先推进 pause_engine 内部 last_frame 到 99，这样 tick(100) 会触发节点
        app.pause_engine.tick(99, tracks, is_running=True, lead_frames=0)
        with patch("app.send_pc_pause_key") as mock_pc, \
             patch.object(app, "_resolve_live_game_window", return_value=None):
            app._maybe_auto_pause(100, is_running=True)
        # 事件被入队（gate=frozen 也不能阻止入队）
        self.assertEqual(len(app._pending_pause_groups), 1)
        self.assertEqual(app._pending_pause_groups.peek().trigger_frame, 100)
        # gate 仍为 frozen（未恢复），且绝不应发键
        self.assertEqual(app._pause_gate, "frozen")
        mock_pc.assert_not_called()

    # ------------------------------------------------------------------
    # 用例 8：大幅帧回退清空 pending queue
    # ------------------------------------------------------------------
    def test_large_frame_rollback_clears_pending_queue(self):
        app = make_app()
        app._queue_pause_events([make_event(0, 200, 199, "A")])
        app._pause_gate = "frozen"
        app._pause_gate_frame = 199
        app._active_pause_group = MagicMock()
        app._pause_verify = {"method_used": "x"}
        # last=200, current=10, reset_threshold=30 → 10+30=40 < 200 触发回退
        app.pause_engine._last_frame = 200
        before_len = len(app._pending_pause_groups)
        self.assertGreater(before_len, 0)
        app._maybe_auto_pause(10, is_running=True)
        self.assertEqual(len(app._pending_pause_groups), 0)
        self.assertIsNone(app._active_pause_group)
        self.assertIsNone(app._pause_gate)
        self.assertIsNone(app._pause_verify)

    # ------------------------------------------------------------------
    # 用例 9：_mark_pause_failed 不重试且清 active
    # ------------------------------------------------------------------
    def test_mark_pause_failed_does_not_retry_and_clears_active(self):
        app = make_app()
        app._pause_gate = "verifying"
        app._pause_gate_frame = 59
        app._active_pause_group = MagicMock(name="active")
        app._pause_verify = {
            "method_used": "SendInput(Escape)",
            "start_frame": 50,
            "start_ts": time.monotonic(),
            "last_frame": 50,
            "stall_count": 0,
            "stall_since": None,
            "trigger_frame": 50,
            "summary": "x",
        }
        with patch("app.send_pc_pause_key") as mock_pc, \
             patch("app.send_adb_pause_key") as mock_adb:
            app._mark_pause_failed(current_frame=59, reason="stall_timeout")
        # 清 gate/verify/active
        self.assertIsNone(app._pause_gate)
        self.assertIsNone(app._pause_verify)
        self.assertIsNone(app._active_pause_group)
        # 不重试：不调用任何输入方法
        mock_pc.assert_not_called()
        mock_adb.assert_not_called()

    # ------------------------------------------------------------------
    # 辅助断言：旧符号必须从 app.py 删除
    # ------------------------------------------------------------------
    def test_old_pause_symbols_removed_from_app(self):
        """旧符号必须以独立 token 形式从 app.py 删除。

        用词边界正则，避免把新符号 ``send_adb_pause_key`` / ``send_pc_pause_key``
        / ``ADB_PAUSE_HOTKEY`` / ``PC_PAUSE_HOTKEY`` 误判为旧符号。
        """
        import inspect
        import re
        from app import TimelineApp

        src = inspect.getsource(TimelineApp)
        forbidden_patterns = [
            r"\b_pc_pause_methods\b",
            r"\b_send_pause_via_method\b",
            r"\b_fail_current_pause_method\b",
            # 旧 send_pause_key 必须不是独立符号；
            # 新 send_adb_pause_key / send_pc_pause_key 允许（用左词边界 + 左非字母数字下划线）
            r"(?<![A-Za-z0-9_])send_pause_key\b",
            r"\bPAUSE_PC_METHODS\b",
            r"\bforce_method\b",
            # 旧 PAUSE_HOTKEY 必须不是独立符号；新 ADB_PAUSE_HOTKEY / PC_PAUSE_HOTKEY 允许
            r"(?<![A-Za-z0-9_])PAUSE_HOTKEY\b",
            r"\bPAUSE_COOLDOWN_SEC\b",
            r"\bawait_freeze\b",
            r"\b_last_pause_send_ts\b",
        ]
        for pat in forbidden_patterns:
            m = re.search(pat, src)
            self.assertIsNone(m, f"app.py 仍包含旧符号 (pattern={pat}): {m.group(0) if m else None}")

    def test_pause_verify_dict_has_no_multi_channel_fields(self):
        """_dispatch 成功后 _pause_verify 只允许 brief 列出的字段。"""
        app = make_app()
        app._queue_pause_events([make_event(0, 60, 59, "A")])
        win = {"hwnd": 1, "title": "明日方舟", "class_name": "UnityWndClass"}
        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", return_value="SendInput(Escape)"), \
             patch("app.looks_like_emulator_window", return_value=False):
            app._dispatch_next_pause_group(current_frame=59)
        v = app._pause_verify
        self.assertIsNotNone(v)
        allowed = {
            "method_used", "start_frame", "start_ts", "last_frame",
            "stall_count", "stall_since", "trigger_frame", "summary",
        }
        extra = set(v.keys()) - allowed
        self.assertEqual(extra, set(), f"_pause_verify 含违禁多通道字段: {extra}")

    # ------------------------------------------------------------------
    # I1 端到端：同一轮 _maybe_auto_pause 释放 frozen 并立即派发队首
    # ------------------------------------------------------------------
    def test_maybe_auto_pause_releases_frozen_and_dispatches_same_tick(self):
        """gate=frozen、gate_frame=N、队列有第二个组、当前帧 N+1：
        单次 _maybe_auto_pause(N+1) 应在该轮内释放 frozen（_update_pause_gate
        把 gate 清成 None），随后步骤 4 派发队首，send_pc_pause_key 恰好一次，
        最终进入 verifying。
        """
        app = make_app()
        app._pause_gate = "frozen"
        app._pause_gate_frame = 59
        app._active_pause_group = MagicMock(name="first_group")
        # 第二个组入队
        app._queue_pause_events([make_event(0, 80, 79, "B")])
        # 配置 tracks 使 tick 在 current_frame=60 时不产生新事件（节点 frame=200），
        # 避免干扰断言；lead=0 来自 fake pause_lead_var
        tracks = [
            {
                "name": "t0",
                "mode": "对轴模式",
                "pause_enabled": True,
                "nodes": [{"frame": 200, "name": "far"}],
            }
        ]
        app.tracks = tracks
        app.pause_engine.tick(59, tracks, is_running=True, lead_frames=0)

        win = {"hwnd": 1, "title": "明日方舟", "class_name": "UnityWndClass"}
        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_pc_pause_key", return_value="SendInput(Escape)") as mock_pc, \
             patch("app.looks_like_emulator_window", return_value=False):
            # 单次调用：frozen 恢复（60>59）→ gate None → 派发队首 B
            app._maybe_auto_pause(60, is_running=True)

        # frozen 已释放，并进入 verifying
        self.assertEqual(app._pause_gate, "verifying")
        # 恰好发一次 PC ESC
        mock_pc.assert_called_once()
        # active 已切到第二个组
        self.assertEqual(app._active_pause_group.trigger_frame, 79)
        # 队列已空
        self.assertEqual(len(app._pending_pause_groups), 0)

    # ------------------------------------------------------------------
    # I1 回归：_process_ws_queue 停帧分支单快照只推进门闩一次（stall_count +1）
    # ------------------------------------------------------------------
    def test_process_ws_queue_stalled_branch_advances_gate_once_per_snapshot(self):
        """I1 回归：同一份停帧快照只应让 _update_pause_gate 的 stall_count +1。

        场景：isRunning=True 且 totalElapsedFrames == _last_game_frame（费用尺
        停帧推送）。_process_ws_queue 的 stalled 分支在历史上会先经
        _maybe_auto_pause 内部调用一次 _update_pause_gate（step 2），随后又在
        同一轮显式调用第二次（旧 app.py 的停帧分支），导致同一份快照被计为
        2 个 stall 样本。本测试驱动真实 _process_ws_queue 主循环（fake queue/
        root），断言单次投递后 stall_count 恰好为 1。旧代码（双调用）会失败
        得到 stall_count=2。
        """
        import queue as _queue

        app = make_app()
        # 用 __new__ 构造的实例没有这些属性，逐个补齐 _process_ws_queue 需要的
        app.is_animating = False
        app.is_inertial_scrolling = False
        app.timeline_offset = 0
        app.inertia_velocity = 0
        app.scaling_factor = 1.0
        app.scaled_pad_m = 0
        # active_track 是只读 property（由 tracks=[] 自然返回 None），不要直接赋值
        app.icons = {}
        # ws_queue：放恰好一份停帧快照
        ws_q = _queue.Queue()
        ws_q.put({
            "type": "snapshot",
            "isRunning": True,
            "totalElapsedFrames": 100,
        })
        app.ws_queue = ws_q
        # root 替身：after 不得真正重调度
        app.root = MagicMock(name="root")
        app._is_time_flowing = False
        # _last_game_frame == 快照帧 → 走停帧分支（旧 app.py 的 elif 分支）
        app._last_game_frame = 100
        app.current_game_frame = 100

        # 进入 verifying，start_frame/last_frame 都为 100，stall_count=0
        base_ts = time.monotonic()
        app._pause_gate = "verifying"
        app._pause_gate_frame = 100
        app._active_pause_group = MagicMock(name="active")
        app._pause_verify = {
            "method_used": "SendInput(Escape)",
            "start_frame": 100,
            "start_ts": base_ts,
            "last_frame": 100,
            "stall_count": 0,
            "stall_since": None,
            "trigger_frame": 99,
            "summary": "x",
        }

        # tracks 为空：停帧分支里 magnet 解锁逻辑空转；_update_display 也无副作用
        app.tracks = []

        # _dispatch_next_pause_group 在 gate=verifying 时直接返回 False，
        # 不会发键，无需 mock 输入通道。_maybe_auto_pause 内部 _update_pause_gate
        # 不会把 gate 清成 None（frozen 恢复才会，当前帧未前进）。

        # 驱动真实主循环（_update_display 用 _distribute_heights/track.update_display，
        # tracks 为空 → 无副作用；finally 里 root.after 只被记录不真正重调度）
        with patch.object(app, "_update_display"):
            app._process_ws_queue()

        # 单份停帧快照：门闩恰好推进一次 → stall_count == 1
        v = app._pause_verify
        self.assertIsNotNone(v, "verifying 不应在单帧抖动下被确认/清空")
        self.assertEqual(
            v["stall_count"], 1,
            f"I1 回归失败：单份停帧快照应只 +1 stall，实际 stall_count={v['stall_count']} "
            f"（双调用旧代码会得到 2）",
        )
        # 仍在 verifying（need_stall=3，单帧远不够），未误判 frozen
        self.assertEqual(app._pause_gate, "verifying")
        # root.after 被重调度恰好一次（_process_ws_queue 的 finally）
        self.assertEqual(app.root.after.call_count, 1)

    # ------------------------------------------------------------------
    # M1 正向：模拟器窗口 → send_adb_pause_key 一次，不调 PC，进入 verifying
    # ------------------------------------------------------------------
    def test_emulator_window_dispatches_adb_not_pc(self):
        app = make_app()
        app._queue_pause_events([make_event(0, 60, 59, "A")])
        group = app._pending_pause_groups.peek()
        win = {"hwnd": 42, "title": "MuMu模拟器", "class_name": "Qt5152QWindowOwnDC"}
        with patch.object(app, "_resolve_live_game_window", return_value=win), \
             patch("app.send_adb_pause_key", return_value="ADB(Space)") as mock_adb, \
             patch("app.send_pc_pause_key") as mock_pc, \
             patch("app.looks_like_emulator_window", return_value=True):
            ok = app._dispatch_next_pause_group(current_frame=59)

        self.assertTrue(ok)
        mock_adb.assert_called_once()
        mock_pc.assert_not_called()
        self.assertEqual(app._pause_gate, "verifying")
        self.assertIs(app._active_pause_group, group)
        self.assertEqual(len(app._pending_pause_groups), 0)

    def test_move_timeline_by_one_frame_breaks_track_magnet(self):
        """键盘/滚轮移动应按传入帧数移动，并解除目标轨道磁铁。"""
        app = make_app()
        app._is_time_flowing = False
        app.timeline_offset = 10.0
        app._update_display = MagicMock()
        magnet_state = {"value": True}
        magnet = MagicMock()
        magnet.get.side_effect = lambda: magnet_state["value"]
        magnet.set.side_effect = lambda value: magnet_state.update(value=bool(value))
        track = SimpleNamespace(magnet_mode=magnet)

        app._move_timeline_by_frames(1, track=track)

        self.assertEqual(app.timeline_offset, 11.0)
        self.assertFalse(magnet_state["value"])
        app._update_display.assert_called_once()

    def test_window_drag_is_limited_to_explicit_drag_zones(self):
        """普通标签不应拖动 HUD；顶栏标记区中的空白仍可拖动。"""
        from app import TimelineApp

        app = TimelineApp.__new__(TimelineApp)
        app.bottom_resize_handle = object()
        app.right_resize_handle = object()
        normal_label = _FakeWidget("TLabel")
        top_bar = _FakeWidget("TFrame", drag_zone=True)
        top_blank = _FakeWidget("Frame", master=top_bar)

        self.assertTrue(app._widget_blocks_window_drag(normal_label))
        self.assertFalse(app._widget_blocks_window_drag(top_blank))

    def test_duplicate_ruler_processes_show_one_warning(self):
        """检测到多个 ruler-app 时应提示一次，并继续安排后续检查。"""
        app = make_app()
        app.root = MagicMock()
        app._duplicate_ruler_warned = False
        app._set_pause_status = MagicMock()

        with patch("app.find_ruler_process_ids", return_value=[16112, 5976]), \
             patch("tkinter.messagebox.showwarning") as warning:
            app._check_duplicate_rulers()
            app._check_duplicate_rulers()

        warning.assert_called_once()
        self.assertTrue(app._duplicate_ruler_warned)
        app._set_pause_status.assert_called_with("费用尺多开: 2 个进程")
        self.assertEqual(app.root.after.call_count, 2)

    def test_lead_controls_are_stacked_in_two_rows(self):
        """提醒提前与暂停提前应各占一行，窄操作面板也能完整显示。"""
        from app import TimelineApp

        root = tk.Tk()
        root.withdraw()
        try:
            app = TimelineApp.__new__(TimelineApp)
            app.scaled_pad_m = 3
            app.scaled_pad_s = 2
            app.scaled_font_normal = -9
            app.pause_lead_var = tk.StringVar(root, value="1")
            app._on_pause_lead_changed = MagicMock()
            active = SimpleNamespace(alert_lead_var=tk.StringVar(root, value="60"))
            parent = ttk.Frame(root)

            app._create_lead_controls(parent, active)
            root.update_idletasks()

            rows = parent.winfo_children()
            self.assertEqual(len(rows), 2)
            self.assertEqual(int(rows[0].grid_info()["row"]), 0)
            self.assertEqual(int(rows[1].grid_info()["row"]), 1)
            labels = [
                child.cget("text")
                for row in rows
                for child in row.winfo_children()
                if isinstance(child, ttk.Label)
            ]
            self.assertEqual(labels, ["提醒提前(帧):", "暂停提前(帧):"])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
