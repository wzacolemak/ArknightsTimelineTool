"""查找 / 绑定游戏窗口（Windows）。

对齐 MAA AttachWindow 找窗思路（AsstProxy.FindWindowsByName）：
  - 只枚举 **可见** 顶层窗
  - PC 客户端默认 **标题精确等于**「明日方舟」
  - 每次发键前重新解析，**禁止**在标题/类名校验失败时仍用过期 hwnd
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# MAA AsstAttachWindowConnect 默认目标标题（精确匹配）
MAA_PC_EXACT_TITLES = ("明日方舟", "Arknights")
# 官服 PC Unity 客户区类名
PC_CLIENT_CLASS_NAMES = ("UnityWndClass",)

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


def _hwnd_to_int(hwnd) -> int:
    """把 HWND / int / c_void_p 稳妥转成 Python int（64 位地址）。"""
    if hwnd is None:
        return 0
    if isinstance(hwnd, int):
        return hwnd
    # ctypes HWND 在 64 位上 value 可能是 bytes / c_void_p
    try:
        return int(hwnd)
    except (TypeError, ValueError):
        pass
    try:
        v = getattr(hwnd, "value", None)
        if v is None:
            return 0
        if isinstance(v, int):
            return v
        if isinstance(v, (bytes, bytearray)):
            return int.from_bytes(v, "little", signed=False)
        return int(v)
    except (TypeError, ValueError):
        return 0


def _window_info(user32, ctypes, wintypes, hwnd) -> Optional[dict]:
    """读取 hwnd 的 title / class / 尺寸；无效则 None。"""
    hwnd_i = _hwnd_to_int(hwnd)
    if not hwnd_i:
        return None
    h = wintypes.HWND(hwnd_i)
    if not user32.IsWindow(h):
        return None
    length = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(max(length, 0) + 1)
    if length > 0:
        user32.GetWindowTextW(h, buf, length + 1)
    title = buf.value or ""
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, cls, 256)
    class_name = cls.value or ""
    rect = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(rect))
    w = max(0, int(rect.right - rect.left))
    hgt = max(0, int(rect.bottom - rect.top))
    visible = bool(user32.IsWindowVisible(h))
    minimized = bool(user32.IsIconic(h))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return {
        "hwnd": hwnd_i,
        "title": title,
        "class_name": class_name,
        "width": w,
        "height": hgt,
        "visible": visible,
        "minimized": minimized,
        "pid": int(pid.value),
    }


def list_top_level_windows(*, visible_only: bool = True) -> List[dict]:
    """枚举顶层窗口（默认仅可见，对齐 MAA EnumWindows + IsWindowVisible）。"""
    ctypes, wintypes, user32 = _user32()
    results: List[dict] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):  # noqa: ANN001
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        info = _window_info(user32, ctypes, wintypes, hwnd)
        if info and info["title"]:
            results.append(info)
        return True

    user32.EnumWindows(enum_proc, 0)
    return results


def _score_pc_client(win: dict) -> int:
    """越高越像官服 PC 客户端（Unity + 明日方舟）。"""
    score = 0
    title = win.get("title") or ""
    cls = win.get("class_name") or ""
    if title in MAA_PC_EXACT_TITLES:
        score += 100
    elif any(t in title for t in MAA_PC_EXACT_TITLES):
        score += 40
    if cls in PC_CLIENT_CLASS_NAMES:
        score += 50
    # 太小的窗多半是工具/残留
    if (win.get("width") or 0) >= 400 and (win.get("height") or 0) >= 300:
        score += 10
    if win.get("minimized"):
        score -= 5
    return score


def find_by_exact_title(titles: Sequence[str]) -> List[dict]:
    """
    对齐 MAA FindWindowsByName：可见顶层窗 + 标题 **全等**。
    返回所有匹配（可能多个）。
    """
    want = [t for t in titles if t]
    if not want:
        return []
    hits = []
    for win in list_top_level_windows(visible_only=True):
        if win["title"] in want:
            hits.append(win)
    return hits


def find_maa_pc_client() -> Optional[dict]:
    """
    按 MAA AttachWindow 默认策略找 PC 客户端：
      标题精确「明日方舟」（及英文 Arknights 兜底），
      多个时优先 UnityWndClass + 较大客户区。
    """
    hits = find_by_exact_title(MAA_PC_EXACT_TITLES)
    if not hits:
        return None
    hits.sort(key=_score_pc_client, reverse=True)
    best = hits[0]
    if len(hits) > 1:
        logger.warning(
            "标题精确匹配到 %d 个窗口，选用 hwnd=%s class=%s title=%r score=%s；其它=%s",
            len(hits),
            best["hwnd"],
            best.get("class_name"),
            best.get("title"),
            _score_pc_client(best),
            [(h["hwnd"], h.get("class_name"), h.get("title")) for h in hits[1:]],
        )
    else:
        logger.info(
            "MAA 式精确标题匹配: hwnd=%s class=%s title=%r pid=%s size=%sx%s",
            best["hwnd"],
            best.get("class_name"),
            best.get("title"),
            best.get("pid"),
            best.get("width"),
            best.get("height"),
        )
    return best


# 关键字模糊时排除的窗口类（终端/资源管理器/浏览器等，避免标题含「明日方舟」误匹配）
_KEYWORD_EXCLUDE_CLASSES = {
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "ConsoleWindowClass",
    "CabinetWClass",  # 资源管理器
    "ExploreWClass",
    "Chrome_WidgetWin_1",
    "MozillaWindowClass",
    "ApplicationFrameWindow",  # UWP 壳
    "Windows.UI.Core.CoreWindow",
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "XamlExplorerHostIslandWindow",
}


def _is_pc_client_bound(bound: Optional[BoundWindow]) -> bool:
    """绑定是否指向官服 PC 客户端（精确标题 + 可选 Unity）。"""
    if not bound:
        return False
    if bound.title not in MAA_PC_EXACT_TITLES:
        return False
    if bound.class_name and bound.class_name not in PC_CLIENT_CLASS_NAMES:
        # 绑定时 class 不是 Unity，可能是误绑
        return False
    return True


def find_by_keywords(keywords: Sequence[str]) -> Optional[dict]:
    """
    模拟器等模糊匹配。对「明日方舟」/「Arknights」**不**做子串匹配
    （那是 MAA 精确标题的职责），避免终端/文档标题误命中。
    """
    keys = [k for k in keywords if k]
    # PC 客户端名只走 exact；这里只留模拟器关键字
    keys = [k for k in keys if k not in MAA_PC_EXACT_TITLES]
    if not keys:
        return None
    candidates = []
    for win in list_top_level_windows(visible_only=True):
        title = win["title"]
        cls = win.get("class_name") or ""
        if cls in _KEYWORD_EXCLUDE_CLASSES:
            continue
        for k in keys:
            if k.lower() in title.lower():
                candidates.append(win)
                break
    if not candidates:
        return None
    candidates.sort(key=_score_pc_client, reverse=True)
    win = candidates[0]
    logger.info(
        "标题关键字匹配窗口: %s class=%s (hwnd=%s score=%s)",
        win["title"],
        win.get("class_name"),
        win["hwnd"],
        _score_pc_client(win),
    )
    return win


def describe_hwnd(hwnd: int) -> Optional[dict]:
    """实时读取 hwnd 属性（发键前校验用）。"""
    try:
        ctypes, wintypes, user32 = _user32()
        return _window_info(user32, ctypes, wintypes, hwnd)
    except Exception as e:  # noqa: BLE001
        logger.warning("describe_hwnd(%s) 失败: %s", hwnd, e)
        return None


def find_bound(bound: Optional[BoundWindow]) -> Optional[dict]:
    """
    解析绑定窗：
      1) 枚举中 title+class 全等
      2) 绑定 hwnd 仍有效 **且** 当前 title/class 与绑定一致（防句柄复用/过期）
    不再在校验失败时盲信旧 hwnd。
    """
    if not bound or not (bound.title or bound.class_name or bound.hwnd):
        return None

    for win in list_top_level_windows(visible_only=True):
        if bound.matches(win["title"], win["class_name"]):
            # 若绑定了 hwnd 且枚举到的不同，优先枚举到的活窗
            if bound.hwnd and win["hwnd"] != bound.hwnd:
                logger.info(
                    "绑定窗句柄已变: 旧 hwnd=%s → 新 hwnd=%s title=%r",
                    bound.hwnd,
                    win["hwnd"],
                    win["title"],
                )
            return win

    # 尝试用绑定 hwnd 自检（必须 title/class 仍对得上）
    if bound.hwnd:
        live = describe_hwnd(bound.hwnd)
        if live and live.get("visible"):
            title_ok = (not bound.title) or (live["title"] == bound.title)
            class_ok = (not bound.class_name) or (live["class_name"] == bound.class_name)
            if title_ok and class_ok:
                return live
            logger.warning(
                "绑定 hwnd=%s 仍有效但属性不匹配: live title=%r class=%r vs bound title=%r class=%r — 丢弃过期绑定",
                bound.hwnd,
                live.get("title"),
                live.get("class_name"),
                bound.title,
                bound.class_name,
            )
        else:
            logger.warning("绑定 hwnd=%s 无效或不可见", bound.hwnd)
    return None


def resolve_game_window(
    keywords: Sequence[str],
    bound: Optional[BoundWindow] = None,
) -> Optional[dict]:
    """
    解析发键目标（每次发键前调用）：
      1) 用户绑定（经活窗校验，title+class）
      2) MAA 式精确标题「明日方舟」
      3) 关键字模糊（仅模拟器关键字；PC 客户端绑定失败时不误匹配终端）
    """
    win = find_bound(bound)
    if win:
        logger.info(
            "使用绑定窗: hwnd=%s class=%s title=%r pid=%s",
            win["hwnd"],
            win.get("class_name"),
            win.get("title"),
            win.get("pid"),
        )
        return win

    if bound:
        # 绑定指向 PC 客户端但当前没找到 → 再试精确标题（游戏重启后 class 仍应是 Unity）。
        # 其它绑定必须保持原目标，避免模拟器失效时把输入改投给 PC 客户端。
        if _is_pc_client_bound(bound):
            win = find_maa_pc_client()
            if win:
                return win
            logger.warning(
                "已绑定 PC 客户端 title=%r 但当前无精确标题窗口，拒绝关键字模糊（防误发到终端/文档）",
                bound.title,
            )
        else:
            logger.warning(
                "已绑定窗口 title=%r class=%r 但当前不可用；拒绝改投其它客户端",
                bound.title,
                bound.class_name,
            )
        return None

    win = find_maa_pc_client()
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
    # 升到根窗（与绑定时一致；MAA 也是附着顶层 hwnd）
    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
    if root:
        hwnd = root
    return _window_info(user32, ctypes, wintypes, hwnd)


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


def refresh_bound_hwnd(bound: BoundWindow) -> Tuple[BoundWindow, Optional[dict]]:
    """
    用 title/class 重新解析活窗并更新 hwnd（游戏重启后句柄会变）。
    返回 (可能更新后的 BoundWindow, 活窗 info 或 None)。
    """
    win = find_bound(bound)
    if not win and _is_pc_client_bound(bound):
        # 仅 PC 绑定允许回退到 MAA 精确标题；模拟器绑定失效时不能静默改绑。
        win = find_maa_pc_client()
    if not win:
        return bound, None
    updated = BoundWindow(
        title=win.get("title") or bound.title,
        class_name=win.get("class_name") or bound.class_name,
        hwnd=int(win["hwnd"]),
    )
    return updated, win
