"""检测本机费用尺进程，避免旧实例占用 2606 导致连接到错误 API。"""
from __future__ import annotations

import sys
from typing import Iterable, List, Optional, Tuple

ProcessEntry = Tuple[int, str]


def _iter_windows_processes() -> Iterable[ProcessEntry]:
    if sys.platform != "win32":
        return []

    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260
    ULONG_PTR = ctypes.c_size_t

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ULONG_PTR),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    )
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    )
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or int(snapshot) == invalid_handle:
        return []

    entries: List[ProcessEntry] = []
    item = PROCESSENTRY32W()
    item.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(item)))
        while ok:
            entries.append((int(item.th32ProcessID), str(item.szExeFile)))
            ok = bool(kernel32.Process32NextW(snapshot, ctypes.byref(item)))
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def find_ruler_process_ids(
    entries: Optional[Iterable[ProcessEntry]] = None,
) -> List[int]:
    """返回所有有效 ``ruler-app.exe`` PID，匹配不区分大小写。"""
    source = _iter_windows_processes() if entries is None else entries
    result = []
    for pid, name in source:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_i > 0 and str(name or "").casefold() == "ruler-app.exe":
            result.append(pid_i)
    return result
