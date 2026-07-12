"""ESC + SendInput 输入层单元测试（mock ctypes/user32，不触真实 Win32）。"""
import ctypes as _ctypes
import ctypes.wintypes as _wintypes
import unittest
from unittest.mock import Mock, patch, call

import hotkey_send

# 真实 ctypes/wintypes，供 _build_sendinput 构造真实 Structure 用。
_REAL_CTYPES = _ctypes
_REAL_WINTYPES = _wintypes


class FakeUser32:
    """最小可用的 user32 替身，只暴露被测路径用到的几个方法。"""

    def __init__(self, foreground=0, is_window=True):
        self.foreground = foreground
        self._is_window = is_window

    def IsWindow(self, hwnd):  # noqa: N802 - Win32 风格命名
        return self._is_window

    def GetForegroundWindow(self):  # noqa: N802
        return self.foreground


class TestPcPauseInput(unittest.TestCase):
    # 1. 前台目标发送 VK_ESCAPE 且不调用 Seize。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._try_foreground_seize")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_foreground_target_sends_escape_without_seize(
        self, ctypes_mock, load_user32, seize, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=123)

        result = hotkey_send.send_pc_pause_key(123, hold_ms=0)

        seize.assert_not_called()
        send_input.assert_called_once()
        # args: (user32, ctypes, wintypes, vk, ...)
        self.assertEqual(send_input.call_args.args[3], 0x1B)
        self.assertIn("SendInput(Escape", result)
        self.assertIn("already_foreground=True", result)
        self.assertIn("focused=True", result)

    # 2. 后台目标先调用 Seize 再发送 VK_ESCAPE。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._try_foreground_seize", return_value=True)
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_background_target_seizes_then_sends_escape(
        self, ctypes_mock, load_user32, seize, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=999)

        result = hotkey_send.send_pc_pause_key(123, hold_ms=0)

        seize.assert_called_once()
        send_input.assert_called_once()
        self.assertEqual(send_input.call_args.args[3], 0x1B)
        self.assertIn("already_foreground=False", result)
        self.assertIn("focused=True", result)

    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._try_foreground_seize", return_value=False)
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_background_target_does_not_send_when_seize_fails(
        self, ctypes_mock, load_user32, seize, send_input
    ):
        """抢前台失败时不能把 ESC 注入当前前台的其它程序。"""
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=999)

        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(123, hold_ms=0)

        seize.assert_called_once()
        send_input.assert_not_called()

    # 3. after_send 在 SendInput 抛异常时仍调用（finally）。
    @patch("hotkey_send._send_via_sendinput", side_effect=OSError("boom"))
    @patch("hotkey_send._try_foreground_seize", return_value=True)
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_after_send_called_even_when_sendinput_raises(
        self, ctypes_mock, load_user32, seize, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=999)
        after = Mock()

        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(123, after_send=after, hold_ms=0)

        after.assert_called_once()

    # 3b. after_send 在前台路径成功时也调用。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_after_send_called_on_success(
        self, ctypes_mock, load_user32, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=123)
        after = Mock()

        hotkey_send.send_pc_pause_key(123, after_send=after, hold_ms=0)

        after.assert_called_once()

    # 3c. before_focus 在前台判断之前调用（前台时不会先去查前台）。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_before_focus_called_before_foreground_check(
        self, ctypes_mock, load_user32, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        order = []

        def fake_user32_get_fg():
            order.append("get_fg")
            return 123

        user32 = FakeUser32(foreground=123)
        user32.GetForegroundWindow = fake_user32_get_fg
        load_user32.return_value = user32

        def before_focus():
            order.append("before_focus")

        hotkey_send.send_pc_pause_key(123, before_focus=before_focus, hold_ms=0)

        self.assertEqual(order, ["before_focus", "get_fg"])

    # VK 模式返回 0 时，在同一 PC 调用内改用 scancode 再试一次。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_vk_failure_retries_with_scancode(
        self, ctypes_mock, load_user32, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=123)
        # 第一次 VK 调用抛 OSError（模拟 SendInput 返回 0），第二次 scancode 成功。
        send_input.side_effect = [OSError("vk returned 0"), None]

        result = hotkey_send.send_pc_pause_key(123, hold_ms=0)

        self.assertEqual(send_input.call_count, 2)
        # 第一次 use_scancode=False，第二次 use_scancode=True。
        self.assertFalse(send_input.call_args_list[0].kwargs["use_scancode"])
        self.assertTrue(send_input.call_args_list[1].kwargs["use_scancode"])
        # 返回值标记使用了 scancode。
        self.assertIn("scancode", result)
        self.assertIn("already_foreground=True", result)

    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_keyup_failure_does_not_retry_a_second_escape(
        self, ctypes_mock, load_user32, send_input
    ):
        """第一次按下已送达、仅抬起失败时不能重发 ESC，避免取消暂停。"""
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=123)
        keyup_error = OSError("key-up failed")
        keyup_error.phase = "up"
        send_input.side_effect = keyup_error

        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(123, hold_ms=0)

        self.assertEqual(send_input.call_count, 1)

    # VK 模式失败、scancode 也失败时抛 OSError（after_send 仍调用）。
    @patch("hotkey_send._send_via_sendinput")
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_vk_and_scancode_both_fail_raise(
        self, ctypes_mock, load_user32, send_input
    ):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(foreground=123)
        send_input.side_effect = [OSError("vk"), OSError("sc")]
        after = Mock()

        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(123, after_send=after, hold_ms=0)
        self.assertEqual(send_input.call_count, 2)
        after.assert_called_once()

    # 4. 无效 hwnd 抛 OSError。
    @patch("hotkey_send._load_user32")
    @patch("hotkey_send._ctypes")
    def test_invalid_hwnd_raises_oserror(self, ctypes_mock, load_user32):
        ctypes_mock.return_value = (Mock(), Mock())
        load_user32.return_value = FakeUser32(is_window=False)

        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(456, hold_ms=0)

    # 4b. 缺失 hwnd（0/None）抛 OSError。
    def test_missing_hwnd_raises_oserror(self):
        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(0, hold_ms=0)
        with self.assertRaises(OSError):
            hotkey_send.send_pc_pause_key(None, hold_ms=0)  # type: ignore[arg-type]

    # 6. 旧 PC 多通道 helper / 入口已不存在。
    def test_removed_pc_message_helpers_are_absent(self):
        self.assertFalse(hasattr(hotkey_send, "send_key_maa_style"))
        self.assertFalse(hasattr(hotkey_send, "_send_via_keybd_event"))
        self.assertFalse(hasattr(hotkey_send, "send_pause_key"))
        self.assertFalse(hasattr(hotkey_send, "resolve_message_target"))
        self.assertFalse(hasattr(hotkey_send, "send_activate_message"))
        self.assertFalse(hasattr(hotkey_send, "make_keydown_lparam"))
        self.assertFalse(hasattr(hotkey_send, "make_keyup_lparam"))

    # 必需接口存在。
    def test_required_public_api_present(self):
        self.assertTrue(callable(getattr(hotkey_send, "send_pc_pause_key", None)))
        self.assertTrue(callable(getattr(hotkey_send, "send_adb_pause_tap", None)))
        self.assertFalse(hasattr(hotkey_send, "send_adb_pause_key"))
        self.assertTrue(callable(getattr(hotkey_send, "is_elevated", None)))
        self.assertTrue(callable(getattr(hotkey_send, "_load_user32", None)))

    # 7. SendInput key-down/key-up + hold_ms 行为可通过 fake 验证。
    def test_send_via_sendinput_down_up_and_hold(self):
        user32 = Mock()
        # SendInput 每次成功返回 1。
        user32.SendInput.return_value = 1
        user32.MapVirtualKeyW.return_value = 0x01
        slept = []

        with patch("hotkey_send.time.sleep", lambda s: slept.append(s)):
            hotkey_send._send_via_sendinput(
                user32,
                _REAL_CTYPES,
                _REAL_WINTYPES,
                0x1B,
                use_scancode=False,
                hold_ms=50,
            )

        # 两次 SendInput：down（flags=0），up（KEYEVENTF_KEYUP=0x0002）
        self.assertEqual(user32.SendInput.call_count, 2)
        # hold_ms>0 时在 down 与 up 之间 sleep 一次。
        self.assertEqual(slept, [0.05])
        # 返回值必须为 1，否则实现应抛 OSError（此用例验证正常路径不抛）。

    # 7b. hold_ms=0 不 sleep。
    def test_send_via_sendinput_no_hold_skips_sleep(self):
        user32 = Mock()
        user32.SendInput.return_value = 1
        user32.MapVirtualKeyW.return_value = 0x01
        slept = []

        with patch("hotkey_send.time.sleep", lambda s: slept.append(s)):
            hotkey_send._send_via_sendinput(
                user32,
                _REAL_CTYPES,
                _REAL_WINTYPES,
                0x1B,
                use_scancode=False,
                hold_ms=0,
            )

        self.assertEqual(slept, [])
        self.assertEqual(user32.SendInput.call_count, 2)

    # 7c. SendInput 返回 0 抛 OSError（key-down 阶段）。
    def test_send_via_sendinput_raises_when_down_returns_zero(self):
        user32 = Mock()
        user32.SendInput.return_value = 0  # 失败
        user32.MapVirtualKeyW.return_value = 0x01

        with patch("hotkey_send.time.sleep"):
            with self.assertRaises(OSError):
                hotkey_send._send_via_sendinput(
                    user32,
                    _REAL_CTYPES,
                    _REAL_WINTYPES,
                    0x1B,
                    use_scancode=False,
                    hold_ms=0,
                )

    # 7d. SendInput key-up 返回 0 抛 OSError。
    def test_send_via_sendinput_raises_when_up_returns_zero(self):
        user32 = Mock()
        # 第一次 down 返回 1，第二次 up 返回 0。
        user32.SendInput.side_effect = [1, 0]
        user32.MapVirtualKeyW.return_value = 0x01

        with patch("hotkey_send.time.sleep"):
            with self.assertRaises(OSError):
                hotkey_send._send_via_sendinput(
                    user32,
                    _REAL_CTYPES,
                    _REAL_WINTYPES,
                    0x1B,
                    use_scancode=False,
                    hold_ms=0,
                )

    # 7e. use_scancode=True 路径应不抛且调用两次 SendInput（down+up）。
    def test_send_via_sendinput_scancode_mode(self):
        user32 = Mock()
        user32.SendInput.return_value = 1
        user32.MapVirtualKeyW.return_value = 0x01

        with patch("hotkey_send.time.sleep"):
            hotkey_send._send_via_sendinput(
                user32,
                _REAL_CTYPES,
                _REAL_WINTYPES,
                0x1B,
                use_scancode=True,
                hold_ms=0,
            )
        self.assertEqual(user32.SendInput.call_count, 2)


class TestSeizeAndFallback(unittest.TestCase):
    # _try_foreground_seize 中 Alt keybd_event 只用于解除前台限制，
    # 不能作为 ESC/Space 暂停通道（此处只验证它存在且不抛异常即可）。
    @patch("hotkey_send._ctypes")
    def test_seize_returns_bool(self, ctypes_mock):
        ctypes_inst = Mock()
        wintypes_inst = Mock()
        ctypes_mock.return_value = (ctypes_inst, wintypes_inst)
        # WinDLL 访问通过 ctypes.windll
        ctypes_inst.windll = Mock()
        ctypes_inst.windll.kernel32.GetCurrentThreadId.return_value = 100
        ctypes_inst.c_size_t = __import__("ctypes").c_size_t
        ctypes_inst.byref = __import__("ctypes").byref
        ctypes_inst.sizeof = __import__("ctypes").sizeof

        user32 = Mock()
        user32.keybd_event = Mock()
        user32.GetForegroundWindow.return_value = 999
        user32.GetWindowThreadProcessId.return_value = 200
        user32.AttachThreadInput.return_value = True
        user32.ShowWindow.return_value = True
        user32.BringWindowToTop.return_value = True
        user32.SetForegroundWindow.return_value = True

        wintypes_inst.HWND = __import__("ctypes.wintypes", fromlist=["wintypes"]).HWND

        with patch("hotkey_send.time.sleep"):
            result = hotkey_send._try_foreground_seize(user32, wintypes_inst, 123)

        self.assertIn(result, (True, False))

    # 早期 keybd_event 抛异常时，_try_foreground_seize 必须返回 False，
    # 且 finally 不得因 cur_tid 未绑定而抛 UnboundLocalError（masking return False）。
    @patch("hotkey_send._ctypes")
    def test_seize_returns_false_when_early_keybd_event_raises(self, ctypes_mock):
        ctypes_inst = Mock()
        wintypes_inst = Mock()
        ctypes_mock.return_value = (ctypes_inst, wintypes_inst)
        ctypes_inst.windll = Mock()
        ctypes_inst.c_size_t = __import__("ctypes").c_size_t
        ctypes_inst.byref = __import__("ctypes").byref
        ctypes_inst.sizeof = __import__("ctypes").sizeof
        wintypes_inst.HWND = __import__(
            "ctypes.wintypes", fromlist=["wintypes"]
        ).HWND

        user32 = Mock()
        # 第一个 keybd_event（Alt key-down）即抛异常 —— 早于 cur_tid 赋值。
        user32.keybd_event = Mock(side_effect=OSError("keybd_event failed"))
        # 如果 finally 引用未绑定的 cur_tid，会触发 UnboundLocalError；
        # 我们断言这里不会被调用到异常，且整体返回 False。
        user32.AttachThreadInput = Mock()

        with patch("hotkey_send.time.sleep"):
            # 不应抛任何异常（既不抛 OSError，也不抛 UnboundLocalError）。
            result = hotkey_send._try_foreground_seize(user32, wintypes_inst, 123)

        self.assertFalse(result)
        # attached 为空（异常发生在 AttachThreadInput 之前），finally 循环不调用 detach。
        user32.AttachThreadInput.assert_not_called()

    # 中段异常（已 Attach 线程后 ShowWindow 抛）也必须返回 False，
    # 且 finally 用已绑定的 cur_tid 正常 detach，不抛清理异常。
    @patch("hotkey_send._ctypes")
    def test_seize_returns_false_when_mid_step_raises_after_attach(
        self, ctypes_mock
    ):
        ctypes_inst = Mock()
        wintypes_inst = Mock()
        ctypes_mock.return_value = (ctypes_inst, wintypes_inst)
        ctypes_inst.windll = Mock()
        ctypes_inst.windll.kernel32.GetCurrentThreadId.return_value = 100
        ctypes_inst.c_size_t = __import__("ctypes").c_size_t
        ctypes_inst.byref = __import__("ctypes").byref
        ctypes_inst.sizeof = __import__("ctypes").sizeof
        wintypes_inst.HWND = __import__(
            "ctypes.wintypes", fromlist=["wintypes"]
        ).HWND

        user32 = Mock()
        user32.keybd_event = Mock()
        user32.GetForegroundWindow.return_value = 999
        user32.GetWindowThreadProcessId.return_value = 200
        user32.AttachThreadInput.return_value = True
        # ShowWindow 在 AttachThreadInput 成功后抛异常，触发 finally detach。
        user32.ShowWindow = Mock(side_effect=OSError("showwindow failed"))

        with patch("hotkey_send.time.sleep"):
            result = hotkey_send._try_foreground_seize(user32, wintypes_inst, 123)

        self.assertFalse(result)
        # 应有一次 Attach(True) 和对应的 Attach(False) detach，不抛清理异常。
        self.assertGreaterEqual(user32.AttachThreadInput.call_count, 2)

    # 结构性防御：_try_foreground_seize 必须在进入 try 之前初始化 cur_tid，
    # 否则早期异常时 finally 的 detach 循环会引用未绑定变量（masking return False）。
    # 通过检查源码在第一个 try 之前存在 cur_tid 赋值来锁定该防御。
    def test_seize_initializes_cur_tid_before_try(self):
        import inspect
        import re

        src = inspect.getsource(hotkey_send._try_foreground_seize)
        try_idx = src.index("try:")
        pre = src[:try_idx]
        # 必须在 try 之前存在形如 "cur_tid = ..." 的行级赋值（排除 docstring 文字）。
        has_init = re.search(r"^\s*cur_tid\s*=\s*", pre, re.MULTILINE) is not None
        self.assertTrue(
            has_init,
            "cur_tid 必须在 try 块之前赋值初始化，以防 finally 引用未绑定变量",
        )

    # is_elevated 在非 win32 平台返回 False，不抛异常。
    def test_is_elevated_non_win32(self):
        with patch("hotkey_send.sys.platform", "linux"):
            self.assertFalse(hotkey_send.is_elevated())


class TestAdbPauseTap(unittest.TestCase):
    @patch("hotkey_send._try_adb_pause_tap", return_value=(1200, 50))
    def test_adb_success(self, adb_pause):
        result = hotkey_send.send_adb_pause_tap()
        adb_pause.assert_called_once_with()
        self.assertEqual(result, "ADB(Tap 1200,50)")

    @patch("hotkey_send._try_adb_pause_tap", return_value=None)
    def test_adb_failure_raises_oserror(self, adb_pause):
        with self.assertRaises(OSError):
            hotkey_send.send_adb_pause_tap()
        adb_pause.assert_called_once()


class TestConfigConverged(unittest.TestCase):
    # 确认 config 已收敛：新增键存在，旧键删除。
    def test_new_pc_pause_keys_present(self):
        import config

        self.assertEqual(getattr(config, "PC_PAUSE_HOTKEY"), "Escape")
        self.assertEqual(getattr(config, "PC_PAUSE_KEY_HOLD_MS"), 50)
        self.assertEqual(getattr(config, "FOCUS_GAME_BEFORE_SEND"), True)
        self.assertEqual(getattr(config, "PAUSE_ENABLED_DEFAULT"), True)
        self.assertEqual(getattr(config, "PAUSE_LEAD_FRAMES"), 1)
        self.assertEqual(getattr(config, "PAUSE_REQUIRE_ADMIN_FOR_PC"), True)

    def test_old_pc_pause_keys_removed(self):
        import config

        self.assertFalse(hasattr(config, "PAUSE_HOTKEY"))
        self.assertFalse(hasattr(config, "PAUSE_COOLDOWN_SEC"))
        self.assertFalse(hasattr(config, "PAUSE_PC_METHODS"))

    def test_retained_pause_verify_keys(self):
        import config

        # 这些应保留。
        for key in (
            "PAUSE_VERIFY_TIMEOUT_SEC",
            "PAUSE_VERIFY_STALL_UPDATES",
            "PAUSE_GATE_MIN_STALL_SEC",
            "PAUSE_VERIFY_FAIL_ADVANCE",
            "PAUSE_LEAD_FRAMES",
            "PAUSE_LEAD_MS",
            "ADB_SERIAL",
        ):
            self.assertTrue(
                hasattr(config, key), f"config 缺少保留键 {key}"
            )

    def test_obsolete_adb_keyevent_settings_removed(self):
        import config

        self.assertFalse(hasattr(config, "ADB_PAUSE_HOTKEY"))
        self.assertFalse(hasattr(config, "ADB_KEYEVENT"))


if __name__ == "__main__":
    unittest.main()
