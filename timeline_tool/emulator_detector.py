"""MAA-inspired emulator and ADB discovery implemented independently."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


Runner = Callable[[Sequence[str], float], tuple[int, str, str]]


KNOWN_ADB_RELATIVE_PATHS = (
    "adb.exe",
    "nox_adb.exe",
    "shell/adb.exe",
    "nx_main/adb.exe",
    "vms/adb.exe",
    "bin/adb.exe",
    "bin/nox_adb.exe",
    "HD-Adb.exe",
    "Engine/ProgramFiles/HD-Adb.exe",
    "../../../nx_main/adb.exe",
    "../vmonitor/bin/adb_server.exe",
    "../../MuMu/emulator/nemu/vmonitor/bin/adb_server.exe",
)

COMMON_EMULATOR_DIRS = (
    r"C:\Program Files\Netease\MuMu Player 12",
    r"C:\Program Files\Netease\MuMu",
    r"C:\LDPlayer\LDPlayer9",
    r"C:\ChangZhi\dnplayer2",
    r"C:\Program Files\Nox\bin",
    r"C:\Program Files\BlueStacks_nxt",
    r"C:\Program Files\Microvirt\MEmu",
)


@dataclass(frozen=True)
class AdbDetectionResult:
    adb_path: str | None
    devices: list[str]
    selected_serial: str | None


def _default_runner(args: Sequence[str], timeout: float = 5.0) -> tuple[int, str, str]:
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
        kwargs["creationflags"] = 0x08000000
    try:
        completed = subprocess.run(**kwargs)
        return completed.returncode, (completed.stdout or "").strip(), (completed.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _existing_adb_paths(directory: str | os.PathLike[str] | None) -> list[str]:
    if not directory:
        return []
    root = Path(directory)
    paths: list[str] = []
    for relative in KNOWN_ADB_RELATIVE_PATHS:
        candidate = root / Path(relative)
        if candidate.is_file():
            paths.append(str(candidate.resolve()))
    return paths


def running_process_executables() -> list[str]:
    """Return executable paths for known emulator processes on Windows."""
    if sys.platform != "win32":
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object {$_.Name -match '^(HD-Player|dnplayer|Nox|MuMuPlayer|MuMuNxDevice|MEmu)(\\.exe)?$'} | "
        "Select-Object -ExpandProperty ExecutablePath"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5.0, creationflags=0x08000000,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def registry_emulator_dirs() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\leidian\LDPlayer9", "InstallDir"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\leidian\LDPlayer9", "InstallDir"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Netease\MuMuPlayer", "InstallPath"),
    )
    found: list[str] = []
    for hive, key_name, value_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            if value:
                found.append(str(value))
        except OSError:
            continue
    return found


def candidate_adb_paths(
    *,
    user_dir: str | os.PathLike[str] | None = None,
    process_executables: Iterable[str | os.PathLike[str]] | None = None,
    registry_dirs: Iterable[str | os.PathLike[str]] | None = None,
    common_dirs: Iterable[str | os.PathLike[str]] | None = None,
    path_adb: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(_existing_adb_paths(user_dir))

    processes = running_process_executables() if process_executables is None else process_executables
    for executable in processes:
        candidates.extend(_existing_adb_paths(Path(executable).parent))

    registries = registry_emulator_dirs() if registry_dirs is None else registry_dirs
    for directory in registries:
        candidates.extend(_existing_adb_paths(directory))

    commons = COMMON_EMULATOR_DIRS if common_dirs is None else common_dirs
    for directory in commons:
        candidates.extend(_existing_adb_paths(directory))

    environment = os.environ if env is None else env
    sdk_root = environment.get("ANDROID_HOME") or environment.get("ANDROID_SDK_ROOT")
    if sdk_root:
        candidates.extend(_existing_adb_paths(Path(sdk_root) / "platform-tools"))

    resolved_path_adb = shutil.which("adb") if path_adb is None else path_adb
    if resolved_path_adb:
        candidates.append(str(resolved_path_adb))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def adb_devices(adb_path: str, runner: Callable[..., tuple[int, str, str]] = _default_runner) -> list[str]:
    code, output, _ = runner([adb_path, "devices"], timeout=5.0)
    if code != 0:
        return []
    devices: list[str] = []
    for line in output.splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[1] == "device":
            devices.append(fields[0])
    return devices


def detect_adb(
    candidates: Iterable[str],
    *,
    selected_serial: str | None = None,
    runner: Callable[..., tuple[int, str, str]] = _default_runner,
) -> AdbDetectionResult:
    for candidate in candidates:
        code, output, _ = runner([candidate, "version"], timeout=3.0)
        if code != 0 or "Android Debug Bridge" not in output:
            continue
        devices = adb_devices(candidate, runner)
        selected = selected_serial if selected_serial in devices else (devices[0] if len(devices) == 1 else None)
        return AdbDetectionResult(candidate, devices, selected)
    return AdbDetectionResult(None, [], None)


def detect_emulator(
    *,
    manual_adb_path: str = "",
    selected_serial: str = "",
    redetect: bool = False,
    candidate_provider: Callable[[], Iterable[str]] | None = None,
    runner: Callable[..., tuple[int, str, str]] = _default_runner,
) -> AdbDetectionResult:
    if manual_adb_path and not redetect:
        devices = adb_devices(manual_adb_path, runner)
        selected = selected_serial or None
        return AdbDetectionResult(manual_adb_path, devices, selected)
    candidates = list(candidate_provider()) if candidate_provider else candidate_adb_paths()
    return detect_adb(candidates, selected_serial=selected_serial or None, runner=runner)
