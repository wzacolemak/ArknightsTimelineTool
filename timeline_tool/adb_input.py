"""
通过 ADB 向安卓模拟器发送按键（暂停回退路径）。

参考费用尺 adb 解析思路：PATH 上的 adb → 常见 MuMu / 雷电自带 adb.exe。
暂停默认 KEYCODE_SPACE=62（与 PC 端 Space 对应）。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Android KeyEvent codes
KEYCODE_SPACE = 62
KEYCODE_ESCAPE = 111  # KEYCODE_ESCAPE
KEYCODE_BACK = 4

# 常见模拟器 adb 相对路径（安装根下）
_EMU_ADB_GLOBS = [
    # MuMu 12
    r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    # 雷电
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer4\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\ChangZhi\dnplayer2\adb.exe",
    # 夜神
    r"C:\Program Files\Nox\bin\adb.exe",
    r"D:\Program Files\Nox\bin\adb.exe",
]

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_cached_adb: Optional[str] = None
_cached_serial: Optional[str] = None


def _run(
    args: Sequence[str],
    *,
    timeout: float = 5.0,
) -> Tuple[int, str, str]:
    kwargs = {
        "args": list(args),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        p = subprocess.run(**kwargs)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def find_adb(extra_candidates: Optional[Sequence[str]] = None) -> Optional[str]:
    """解析 adb 可执行文件路径。"""
    global _cached_adb
    if _cached_adb and os.path.isfile(_cached_adb):
        return _cached_adb
    if _cached_adb == "adb" and shutil.which("adb"):
        return "adb"

    candidates: List[str] = []
    if extra_candidates:
        candidates.extend(extra_candidates)
    which = shutil.which("adb")
    if which:
        candidates.append(which)
    candidates.append("adb")
    candidates.extend(_EMU_ADB_GLOBS)
    # 环境变量
    env_adb = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if env_adb:
        candidates.append(os.path.join(env_adb, "platform-tools", "adb.exe"))
        candidates.append(os.path.join(env_adb, "platform-tools", "adb"))

    for c in candidates:
        if not c:
            continue
        if c == "adb" or shutil.which(c):
            code, out, err = _run([c, "version"], timeout=3.0)
            if code == 0:
                _cached_adb = c if c != "adb" else (shutil.which("adb") or "adb")
                logger.info("ADB 已解析: %s (%s)", _cached_adb, out.splitlines()[0] if out else "")
                return _cached_adb
        if os.path.isfile(c):
            code, out, err = _run([c, "version"], timeout=3.0)
            if code == 0:
                _cached_adb = c
                logger.info("ADB 已解析: %s", c)
                return c
    logger.warning("未找到可用 adb（PATH / 模拟器目录）")
    return None


def list_devices(adb_path: Optional[str] = None) -> List[str]:
    """返回状态为 device 的 serial 列表。"""
    adb = adb_path or find_adb()
    if not adb:
        return []
    code, out, err = _run([adb, "devices"], timeout=5.0)
    if code != 0:
        logger.warning("adb devices 失败: %s %s", err, out)
        return []
    serials: List[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def pick_serial(
    preferred: Optional[str] = None,
    adb_path: Optional[str] = None,
) -> Optional[str]:
    global _cached_serial
    adb = adb_path or find_adb()
    if not adb:
        return None
    devices = list_devices(adb)
    if preferred:
        # 尝试 connect 常见 TCP serial
        if preferred not in devices and (":" in preferred or preferred.replace(".", "").isdigit()):
            _run([adb, "connect", preferred], timeout=5.0)
            devices = list_devices(adb)
        if preferred in devices:
            _cached_serial = preferred
            return preferred
    if _cached_serial and _cached_serial in devices:
        return _cached_serial
    if not devices:
        # 试常见模拟器端口
        for port in (16384, 7555, 5555, 62001, 5554):
            serial = f"127.0.0.1:{port}"
            _run([adb, "connect", serial], timeout=2.0)
        devices = list_devices(adb)
    if devices:
        _cached_serial = devices[0]
        logger.info("选用 ADB 设备: %s (共 %d 台)", _cached_serial, len(devices))
        return _cached_serial
    return None


def send_keyevent(
    keycode: int = KEYCODE_SPACE,
    *,
    serial: Optional[str] = None,
    adb_path: Optional[str] = None,
) -> None:
    """
    adb shell input keyevent <code>
    失败抛 OSError。
    """
    adb = adb_path or find_adb()
    if not adb:
        raise OSError("未找到 adb")
    dev = pick_serial(serial, adb)
    if not dev:
        raise OSError("无可用 ADB 设备（请开模拟器并开 ADB 调试）")
    args = [adb, "-s", dev, "shell", "input", "keyevent", str(int(keycode))]
    code, out, err = _run(args, timeout=5.0)
    if code != 0:
        raise OSError(f"adb keyevent 失败 code={code} err={err or out}")
    logger.info("已通过 ADB 发送 keyevent %s → %s", keycode, dev)


def hotkey_to_keycode(hotkey: str) -> int:
    key = (hotkey or "Space").strip().lower()
    if key in {"space", " "}:
        return KEYCODE_SPACE
    if key in {"escape", "esc"}:
        return KEYCODE_ESCAPE
    if key == "back":
        return KEYCODE_BACK
    # 单字母：Android 有 KEYCODE_A=29 ... 简单映射
    if len(key) == 1 and "a" <= key <= "z":
        return 29 + (ord(key) - ord("a"))
    return KEYCODE_SPACE


def looks_like_emulator_window(title: str, class_name: str = "") -> bool:
    t = (title or "").lower()
    c = (class_name or "").lower()
    keys = (
        "mumu", "雷电", "ldplayer", "nox", "夜神", "bluestacks", "memu",
        "emulator", "模拟器", "dnplayer",
    )
    return any(k in t for k in keys) or any(k in c for k in keys)
