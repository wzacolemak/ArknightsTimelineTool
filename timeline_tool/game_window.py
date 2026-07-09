"""查找 / 绑定游戏窗口（Windows）。"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "明日方舟",
    "Arknights",
    "MuMu",
    "雷电",
    "LDPlayer",
    "夜神",
    "Nox",
    "BlueStacks",
    "mumu",
    "emulator",
]


@dataclass
class BoundWindow:
    title: str = ""
    class_name: str = ""
    hwnd: int = 0

    def matches(self, title: str, class_name: str) -> bool:
        if self.title and self.title != title:
            return False
        if self.class_name and self.class_name != class_name:
            return False
        return bool(self.title or self.class_name)


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    return ctypes, wintypes, user32


def list_top_level_windows() -> List[dict]:
    """枚举可见顶层窗口。"""
    ctypes, wintypes, user32 = _user32()
    results: List[dict] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        results.append({"hwnd": int(hwnd), "title": title, "class_name": cls.value})
        return True

    user32.EnumWindows(enum_proc, 0)
    return results


def find_by_keywords(keywords: Sequence[str]) -> Optional[dict]:
    keys = [k for k in keywords if k]
    if not keys:
        return None
    for win in list_top_level_windows():
        title = win["title"]
        for k in keys:
            if k.lower() in title.lower():
                logger.info("标题匹配窗口: %s (hwnd=%s)", title, win["hwnd"])
                return win
    return None


def find_bound(bound: Optional[BoundWindow]) -> Optional[dict]:
    if not bound or not (bound.title or bound.class_name):
        return None
    for win in list_top_level_windows():
        if bound.matches(win["title"], win["class_name"]):
            return win
    # 若绑定了 hwnd 且仍有效
    if bound.hwnd:
        ctypes, wintypes, user32 = _user32()
        if user32.IsWindow(wintypes.HWND(bound.hwnd)):
            return {
                "hwnd": bound.hwnd,
                "title": bound.title,
                "class_name": bound.class_name,
            }
    return None


def resolve_game_window(
    keywords: Sequence[str],
    bound: Optional[BoundWindow] = None,
) -> Optional[dict]:
    """优先已绑定窗，否则关键字匹配。"""
    win = find_bound(bound)
    if win:
        return win
    return find_by_keywords(keywords)


def window_from_point(x: int, y: int) -> Optional[dict]:
    ctypes, wintypes, user32 = _user32()

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT(x, y)
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return None
    # 升到根窗
    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
    if root:
        hwnd = root
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(length, 0) + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    return {"hwnd": int(hwnd), "title": buf.value, "class_name": cls.value}


def pick_window_under_cursor(timeout_sec: float = 3.0) -> Optional[dict]:
    """
    等待 timeout_sec，取当前光标下窗口（调用方应提示用户在倒计时内点击目标）。
    简单实现：超时后采样一次光标位置对应窗口（不拦截点击）。
    """
    ctypes, wintypes, user32 = _user32()
    deadline = time.time() + timeout_sec
    last: Optional[dict] = None
    while time.time() < deadline:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        last = window_from_point(pt.x, pt.y)
        time.sleep(0.05)
    return last


def load_bound(path: str) -> Optional[BoundWindow]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BoundWindow(
            title=data.get("title", ""),
            class_name=data.get("class_name", ""),
            hwnd=int(data.get("hwnd") or 0),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("读取绑定窗口失败: %s", e)
        return None


def save_bound(path: str, bound: BoundWindow) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(bound), f, ensure_ascii=False, indent=2)
    logger.info("已保存绑定窗口: %s", bound)
