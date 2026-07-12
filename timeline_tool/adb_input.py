"""
通过 ADB 向安卓模拟器发送触控操作。

参考费用尺 adb 解析思路：PATH 上的 adb → 常见 MuMu / 雷电自带 adb.exe。
自动暂停点击 MAA 的 1280×720 基准暂停按钮区域中心，并按设备分辨率缩放。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# MAA resource/tasks/tasks.json 的 BattlePause 区域为 [1170, 20, 60, 60]。
# 使用区域中心可避免随机点落在按钮边缘。
_BASE_WIDTH = 1280
_BASE_HEIGHT = 720
_PAUSE_POINT = (1200, 50)
_SIZE_RE = re.compile(r"(\d+)\s*x\s*(\d+)", re.IGNORECASE)

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


def find_adb(
    extra_candidates: Optional[Sequence[str]] = None,
    *,
    configured_adb_path: Optional[str] = None,
    emulator_dir: Optional[str] = None,
) -> Optional[str]:
    """解析 adb 可执行文件路径。"""
    global _cached_adb

    candidates: List[str] = []
    if configured_adb_path:
        candidates.append(os.fspath(configured_adb_path))
    if emulator_dir:
        root = os.fspath(emulator_dir)
        from emulator_detector import KNOWN_ADB_RELATIVE_PATHS

        for relative in KNOWN_ADB_RELATIVE_PATHS:
            candidates.append(os.path.join(root, *relative.split("/")))
    if extra_candidates:
        candidates.extend(extra_candidates)
    if not configured_adb_path and not emulator_dir:
        if _cached_adb and os.path.isfile(_cached_adb):
            return _cached_adb
        if _cached_adb == "adb" and shutil.which("adb"):
            return "adb"
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
        is_path_candidate = os.path.isfile(c) or bool(shutil.which(c))
        if c != "adb" and not is_path_candidate:
            continue
        code, out, err = _run([c, "version"], timeout=3.0)
        if code == 0:
            _cached_adb = c if c != "adb" else (shutil.which("adb") or "adb")
            logger.info("ADB 已解析: %s (%s)", _cached_adb, out.splitlines()[0] if out else "")
            return _cached_adb
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
    if len(devices) == 1:
        _cached_serial = devices[0]
        logger.info("选用 ADB 设备: %s", _cached_serial)
        return _cached_serial
    if len(devices) > 1:
        logger.warning("发现多台 ADB 设备，必须在设置中明确选择: %s", devices)
    return None


def send_pause_tap(
    *,
    serial: Optional[str] = None,
    adb_path: Optional[str] = None,
    emulator_dir: Optional[str] = None,
) -> Tuple[int, int]:
    """
    点击模拟器内的明日方舟暂停按钮，返回实际点击坐标。

    坐标以 MAA 的 1280×720 BattlePause 区域中心为基准。ADB 的 `wm size`
    若同时返回 Physical size 与 Override size，使用最后一个（当前逻辑分辨率）。
    """
    adb = find_adb(configured_adb_path=adb_path, emulator_dir=emulator_dir)
    if not adb:
        raise OSError("未找到 adb")
    dev = pick_serial(serial, adb)
    if not dev:
        raise OSError("无可用 ADB 设备（请开模拟器并开 ADB 调试）")

    code, out, err = _run(
        [adb, "-s", dev, "shell", "wm", "size"],
        timeout=5.0,
    )
    if code != 0:
        raise OSError(f"读取 ADB 分辨率失败 code={code} err={err or out}")
    matches = _SIZE_RE.findall(out)
    if not matches:
        raise OSError(f"无法解析 ADB 分辨率: {out or err}")
    width, height = (int(value) for value in matches[-1])
    if width < _BASE_WIDTH or height < _BASE_HEIGHT:
        raise OSError(f"模拟器分辨率过低: {width}x{height}，至少需要 1280x720")
    if width * _BASE_HEIGHT != height * _BASE_WIDTH:
        raise OSError(f"模拟器分辨率不是 16:9: {width}x{height}")

    scale = height / _BASE_HEIGHT
    x = int(_PAUSE_POINT[0] * scale)
    y = int(_PAUSE_POINT[1] * scale)
    args = [adb, "-s", dev, "shell", "input", "tap", str(x), str(y)]
    code, out, err = _run(args, timeout=5.0)
    if code != 0:
        raise OSError(f"ADB 点击暂停失败 code={code} err={err or out}")
    logger.info("已通过 ADB 点击暂停 (%s,%s) → %s [%sx%s]", x, y, dev, width, height)
    return x, y


def looks_like_emulator_window(title: str, class_name: str = "") -> bool:
    t = (title or "").lower()
    c = (class_name or "").lower()
    keys = (
        "mumu", "雷电", "ldplayer", "nox", "夜神", "bluestacks", "memu",
        "emulator", "模拟器", "dnplayer",
    )
    return any(k in t for k in keys) or any(k in c for k in keys)
