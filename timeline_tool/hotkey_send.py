"""
向游戏窗口发送暂停热键。

PC 客户端：只使用 ESC + Windows SendInput。
  - 目标 HWND 已是前台时直接发送，不调用 Seize，不做固定置前等待。
  - 目标不在前台时调用 _try_foreground_seize 抢前台后再 SendInput。
  - SendInput 若 VK 模式返回 0，可在同一次调用内改用 scancode 再试一次；
    不会切换到其他输入 API（无窗口消息、无 keybd_event 暂停通道，
    Seize 中解除前台限制的 Alt tap 除外）。

模拟器：保留显式 ADB Space 路径，不作为 PC 失败回退。

约束：
  - 不复制 AFA GPL 源码，不引入 AutoHotkey 运行时。
  - _try_foreground_seize 中允许保留 Alt keybd_event，它只用于解除
    Windows 前台限制，不能用来发送 ESC/Space。
  - Python 3.8 兼容。
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

VK_MAP = {
    "space": 0x20,
    " ": 0x20,
    "f": 0x46,
    "escape": 0x1B,
    "esc": 0x1B,
    "p": 0x50,
}

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

VK_MENU = 0x12

ctypes_module = None


class SendInputError(OSError):
    """标记 SendInput 在按下或抬起阶段失败，供调用方安全决定是否回退。"""

    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase


def _vk(hotkey: str) -> int:
    key = (hotkey or "Space").strip().lower()
    if key in VK_MAP:
        return VK_MAP[key]
    if len(key) == 1:
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 12:
            return 0x70 + (n - 1)
    raise ValueError(f"不支持的热键: {hotkey!r}")


def _ctypes():
    global ctypes_module
    if ctypes_module is None:
        import ctypes
        from ctypes import wintypes

        ctypes_module = (ctypes, wintypes)
    return ctypes_module


def _build_sendinput(ctypes, wintypes):
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

    return KEYBDINPUT, INPUT


def _load_user32(ctypes, wintypes):
    """集中配置 user32 原型，便于测试 mock。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    return user32


def _try_foreground_seize(user32, wintypes, hwnd: int) -> bool:
    """
    Seize 路径：真抢前台（SendInput 需要前台才能稳定生效）。

    Alt keybd_event 仅用于解除 Windows 前台限制，不会发送 ESC/Space。
    用 finally 保证所有已 Attach 的线程被 detach。
    cur_tid / attached 在 try 之前初始化，避免早期异常时 finally 引用未绑定变量
    而 masking 掉预期的 return False。
    """
    ctypes, _ = _ctypes()
    attached = []
    cur_tid = 0
    try:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        tgt_tid = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        for tid in (fg_tid, tgt_tid):
            if tid and tid != cur_tid:
                if user32.AttachThreadInput(cur_tid, tid, True):
                    attached.append(tid)
        user32.ShowWindow(wintypes.HWND(hwnd), 9)
        user32.BringWindowToTop(wintypes.HWND(hwnd))
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
        time.sleep(0.06)
        fg2 = int(user32.GetForegroundWindow() or 0)
        ok = fg2 == int(hwnd)
        logger.info("Seize 置前 hwnd=%s foreground=%s ok=%s", hwnd, fg2, ok)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("Seize 置前失败: %s", e)
        return False
    finally:
        # cur_tid 已在 try 之前初始化，即使 keybd_event 早期抛异常也能安全 detach。
        for tid in attached:
            try:
                user32.AttachThreadInput(cur_tid, tid, False)
            except Exception:  # noqa: BLE001
                pass


def _send_via_sendinput(
    user32,
    ctypes,
    wintypes,
    vk: int,
    use_scancode: bool,
    hold_ms: int = 50,
) -> None:
    """
    1. 发送 key-down。
    2. hold_ms > 0 时 sleep hold_ms / 1000.0。
    3. 发送 key-up。
    4. 每次 SendInput 返回值必须为 1，否则抛 OSError。
    """
    KEYBDINPUT, INPUT = _build_sendinput(ctypes, wintypes)
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF

    def one(flags: int, phase: str) -> None:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        if use_scancode:
            inp.union.ki = KEYBDINPUT(0, scan, flags | KEYEVENTF_SCANCODE, 0, 0)
        else:
            inp.union.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetLastError(0)
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if n != 1:
            raise SendInputError(
                phase,
                f"SendInput n={n} err={ctypes.get_last_error()} sc={use_scancode} phase={phase}",
            )

    one(0, "down")
    if hold_ms > 0:
        time.sleep(hold_ms / 1000.0)
    one(KEYEVENTF_KEYUP, "up")


def _try_adb_pause(hotkey: str) -> bool:
    """显式 ADB 暂停路径（仅模拟器使用，不作为 PC 回退）。"""
    try:
        import config as _cfg

        if not getattr(_cfg, "ADB_PAUSE_ENABLED", True):
            return False
        from adb_input import hotkey_to_keycode, send_keyevent

        serial = getattr(_cfg, "ADB_SERIAL", "") or None
        keycode = getattr(_cfg, "ADB_KEYEVENT", None)
        if keycode is None:
            keycode = hotkey_to_keycode(hotkey)
        send_keyevent(int(keycode), serial=serial or None)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("ADB 暂停失败: %s", e)
        return False


def is_elevated() -> bool:
    """当前进程是否以管理员运行（UAC elevated）。"""
    if sys.platform != "win32":
        return False
    try:
        ctypes, _ = _ctypes()
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def send_pc_pause_key(
    hwnd: int,
    before_focus: Optional[Callable[[], None]] = None,
    after_send: Optional[Callable[[], None]] = None,
    hold_ms: int = 50,
) -> str:
    """
    向 PC 游戏窗口发送一次 ESC + SendInput。

    1. hwnd 缺失或无效时抛 OSError。
    2. before_focus 在前台判断之前调用。
    3. 若目标已前台，直接 SendInput Escape，不调用 Seize。
    4. 若目标不在前台，先 Seize 再 SendInput Escape。
    5. after_send 必须在 finally 中调用。
    6. 不自动发送 Space。

    返回值形如:
      "SendInput(Escape,already_foreground=True|False,focused=True|False)"
    """
    if not hwnd:
        raise OSError("未提供游戏窗口 hwnd")
    ctypes, wintypes = _ctypes()
    user32 = _load_user32(ctypes, wintypes)
    target = wintypes.HWND(int(hwnd))
    if not user32.IsWindow(target):
        raise OSError(f"无效 hwnd={hwnd}")

    try:
        if before_focus:
            before_focus()
        foreground = int(user32.GetForegroundWindow() or 0)
        already_foreground = foreground == int(hwnd)
        focused = already_foreground
        if not already_foreground:
            focused = _try_foreground_seize(user32, wintypes, int(hwnd))
            if not focused:
                raise OSError(f"无法将游戏窗口置前 hwnd={hwnd}；已取消发送 ESC")

        vk = _vk("Escape")
        # VK 模式优先；返回 0 时在同一 PC 调用内改用 scancode 再试一次，
        # 不切换到其他输入 API。
        try:
            _send_via_sendinput(
                user32,
                ctypes,
                wintypes,
                vk,
                use_scancode=False,
                hold_ms=hold_ms,
            )
            used_scancode = False
        except OSError as e:
            # key-down 已成功而 key-up 失败时，重发完整 ESC 会导致第二次按键
            # 取消刚刚的暂停；此时仅把失败上报，由上层处理，不再回退编码。
            if getattr(e, "phase", None) == "up":
                raise
            logger.warning("SendInput VK 模式失败，改用 scancode: %s", e)
            _send_via_sendinput(
                user32,
                ctypes,
                wintypes,
                vk,
                use_scancode=True,
                hold_ms=hold_ms,
            )
            used_scancode = True
        method = (
            "SendInput(Escape,"
            f"already_foreground={already_foreground},focused={focused})"
        )
        if used_scancode:
            method += ",scancode"
        logger.info("已发送 PC 自动暂停键 via %s", method)
        return method
    finally:
        if after_send:
            after_send()


def send_adb_pause_key(hotkey: str = "Space") -> str:
    """
    显式向模拟器发送一次 ADB 暂停键。

    只调用现有 ADB helper；失败抛 OSError，成功返回 "ADB(Space)"。
    不作为 PC 失败回退。
    """
    if not _try_adb_pause(hotkey):
        raise OSError(f"ADB 暂停失败 hotkey={hotkey}")
    logger.info("已发送模拟器自动暂停键 %s via ADB", hotkey)
    return "ADB(Space)"
