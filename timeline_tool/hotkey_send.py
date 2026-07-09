"""向游戏窗口发送暂停热键（Windows SendInput）。"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Virtual-Key codes (subset)
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


def _vk(hotkey: str) -> int:
    key = (hotkey or "Space").strip().lower()
    if key in VK_MAP:
        return VK_MAP[key]
    if len(key) == 1:
        return ord(key.upper())
    # F1-F12
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 12:
            return 0x70 + (n - 1)
    raise ValueError(f"不支持的热键: {hotkey!r}")


def send_pause_key(
    hotkey: str = "Space",
    hwnd: Optional[int] = None,
    focus_before_send: bool = True,
) -> None:
    """
    使用 SendInput 发送一次按键。
    hwnd 可选：focus_before_send 时先尝试置前。
    """
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError as e:
        raise RuntimeError("需要 Windows + ctypes") from e

    user32 = ctypes.windll.user32
    vk = _vk(hotkey)

    if focus_before_send and hwnd:
        try:
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            time.sleep(0.02)
        except Exception as e:  # noqa: BLE001
            logger.warning("SetForegroundWindow 失败: %s", e)

    # INPUT structure for SendInput
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _I)]

    def _send(flags: int) -> None:
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if n != 1:
            err = ctypes.get_last_error()
            raise OSError(f"SendInput 失败 n={n} err={err}")

    _send(0)
    time.sleep(0.01)
    _send(KEYEVENTF_KEYUP)
    logger.info("已发送暂停键 %s (vk=0x%02X) hwnd=%s", hotkey, vk, hwnd)
