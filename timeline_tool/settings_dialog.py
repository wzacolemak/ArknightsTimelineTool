"""White Windows-style application settings dialog."""

from __future__ import annotations

import copy
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from emulator_detector import adb_devices, candidate_adb_paths, detect_adb
from settings_manager import (
    DEFAULT_SHORTCUTS,
    SettingsValidationError,
    default_settings,
    get_setting,
    set_setting,
    validate_settings,
)
from shortcut_utils import display_sequence, format_key_event


TAB_TITLES = ["常规", "提醒", "时间轴", "快捷键", "费用尺", "自动暂停", "模拟器"]

SHORTCUT_LABELS = {
    "move_backward": "向前移动时间轴",
    "move_forward": "向后移动时间轴",
    "previous_node": "跳转到前一个节点",
    "next_node": "跳转到后一个节点",
    "zoom_track_in": "放大当前轨道",
    "zoom_track_out": "缩小当前轨道",
    "zoom_all_in": "放大全部轨道",
    "zoom_all_out": "缩小全部轨道",
}


class SettingsDialog:
    def __init__(self, parent, settings, on_save):
        self.parent = parent
        self.original = validate_settings(settings)
        self.on_save = on_save
        self.variables: dict[str, tk.Variable] = {}
        self.shortcut_display_vars: dict[str, tk.StringVar] = {}
        self.shortcut_entries: dict[str, ttk.Entry] = {}
        self._shortcut_capture_path: str | None = None
        self._shortcut_capture_original: str | None = None
        self.tab_titles = list(TAB_TITLES)

        self.window = tk.Toplevel(parent, background="white")
        self.window.title("设置")
        self.window.geometry("720x560")
        self.window.minsize(660, 500)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

        self._configure_styles()
        self.notebook = ttk.Notebook(self.window, style="Settings.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        self.tabs = {}
        for title in TAB_TITLES:
            tab = ttk.Frame(self.notebook, style="Settings.TFrame", padding=16)
            self.notebook.add(tab, text=title)
            self.tabs[title] = tab

        self._build_general_tab()
        self._build_alerts_tab()
        self._build_timeline_tab()
        self._build_shortcuts_tab()
        self._build_ruler_tab()
        self._build_auto_pause_tab()
        self._build_emulator_tab()
        self.window.bind("<KeyPress>", self._handle_shortcut_key, add="+")

        bottom = ttk.Frame(self.window, style="Settings.TFrame", padding=(14, 6, 14, 14))
        bottom.pack(fill="x")
        self.error_label = ttk.Label(bottom, text="", style="Settings.Error.TLabel")
        self.error_label.pack(side="left", fill="x", expand=True)
        self.default_button = ttk.Button(bottom, text="恢复默认", command=self._restore_defaults)
        self.default_button.pack(side="left", padx=4)
        self.cancel_button = ttk.Button(bottom, text="取消", command=self._cancel)
        self.cancel_button.pack(side="left", padx=4)
        self.save_button = ttk.Button(bottom, text="保存", command=self._save)
        self.save_button.pack(side="left", padx=4)

    def _configure_styles(self):
        style = ttk.Style(self.window)
        style.configure("Settings.TFrame", background="white")
        style.configure("Settings.TLabel", background="white", foreground="#202020")
        style.configure("Settings.Error.TLabel", background="white", foreground="#c62828")
        style.configure("Settings.TCheckbutton", background="white", foreground="#202020")
        style.configure("Settings.TNotebook", background="white")
        style.configure("Settings.TNotebook.Tab", padding=(14, 7))

    def _variable(self, path, *, boolean=False):
        value = get_setting(self.original, path)
        var = tk.BooleanVar(self.window, value=bool(value)) if boolean else tk.StringVar(self.window, value=str(value))
        self.variables[path] = var
        return var

    def _entry_row(self, tab, row, label, path, *, width=28, note=None):
        ttk.Label(tab, text=label, style="Settings.TLabel").grid(row=row, column=0, sticky="w", pady=6)
        entry = ttk.Entry(tab, textvariable=self._variable(path), width=width)
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6)
        if note:
            ttk.Label(tab, text=note, style="Settings.TLabel", wraplength=300).grid(
                row=row, column=2, sticky="w", padx=(10, 0), pady=6
            )
        tab.columnconfigure(1, weight=1)
        return entry

    def _check_row(self, tab, row, label, path):
        check = ttk.Checkbutton(
            tab, text=label, variable=self._variable(path, boolean=True), style="Settings.TCheckbutton"
        )
        check.grid(row=row, column=0, columnspan=3, sticky="w", pady=6)
        return check

    def _build_general_tab(self):
        self._entry_row(self.tabs["常规"], 0, "窗口透明度", "general.opacity", note="0.30 至 1.00")

    def _build_alerts_tab(self):
        tab = self.tabs["提醒"]
        self._check_row(tab, 0, "启用声音提醒", "alerts.sound_enabled")
        self._check_row(tab, 1, "启用视觉提醒", "alerts.visual_enabled")
        self._entry_row(tab, 2, "提醒提前帧数", "alerts.alert_lead_frames", note="0 至 300")
        self._entry_row(tab, 3, "暂停提前帧数", "alerts.pause_lead_frames", note="0 至 30")

    def _build_timeline_tab(self):
        tab = self.tabs["时间轴"]
        rows = (
            ("节点选中范围", "timeline.node_find_tolerance", "0 至 30 帧"),
            ("单击节点吸附范围", "timeline.node_click_tolerance", "0 至 30 帧"),
            ("键盘移动步数", "timeline.keyboard_scroll_step", "1 至 30 帧"),
            ("鼠标滚轮移动步数", "timeline.mouse_wheel_scroll_step", "1 至 30 帧"),
        )
        for row, (label, path, note) in enumerate(rows):
            self._entry_row(tab, row, label, path, note=note)

    def _build_shortcuts_tab(self):
        tab = self.tabs["快捷键"]
        for row, (action, label) in enumerate(SHORTCUT_LABELS.items()):
            path = f"shortcuts.{action}"
            ttk.Label(tab, text=label, style="Settings.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            sequence_var = self._variable(path)
            display_var = tk.StringVar(self.window, value=display_sequence(sequence_var.get()))
            self.shortcut_display_vars[path] = display_var
            entry = ttk.Entry(tab, textvariable=display_var, width=24, state="readonly")
            self.shortcut_entries[path] = entry
            entry.grid(row=row, column=1, sticky="ew", padx=10, pady=5)
            entry.bind("<Button-1>", lambda _event, p=path: self._begin_shortcut_capture(p))
            entry.bind("<FocusIn>", lambda _event, p=path: self._begin_shortcut_capture(p))
            ttk.Button(
                tab, text="默认", width=6,
                command=lambda p=path, a=action: self._set_shortcut(p, DEFAULT_SHORTCUTS[a]),
            ).grid(row=row, column=2, pady=5)
        tab.columnconfigure(1, weight=1)
        ttk.Button(tab, text="全部恢复默认", command=self._restore_default_shortcuts).grid(
            row=len(SHORTCUT_LABELS), column=1, sticky="e", pady=(12, 0)
        )

    def _begin_shortcut_capture(self, path):
        if self._shortcut_capture_path and self._shortcut_capture_path != path:
            previous = self._shortcut_capture_path
            self.shortcut_display_vars[previous].set(display_sequence(self.variables[previous].get()))
        self._shortcut_capture_path = path
        self._shortcut_capture_original = self.variables[path].get()
        self.shortcut_display_vars[path].set("请按快捷键…")
        self.shortcut_entries[path].focus_set()
        return "break"

    def _handle_shortcut_key(self, event):
        path = self._shortcut_capture_path
        if not path:
            return None
        if str(getattr(event, "keysym", "")).casefold() == "escape":
            original = self._shortcut_capture_original or self.variables[path].get()
            self.variables[path].set(original)
            self.shortcut_display_vars[path].set(display_sequence(original))
            self._shortcut_capture_path = None
            self._shortcut_capture_original = None
            return "break"
        sequence = format_key_event(event)
        if sequence:
            self._set_shortcut(path, sequence)
        return "break"

    def _set_shortcut(self, path, sequence):
        self.variables[path].set(sequence)
        self.shortcut_display_vars[path].set(display_sequence(sequence))
        if self._shortcut_capture_path == path:
            self._shortcut_capture_path = None
            self._shortcut_capture_original = None

    def _restore_default_shortcuts(self):
        for action, sequence in DEFAULT_SHORTCUTS.items():
            self._set_shortcut(f"shortcuts.{action}", sequence)

    def _build_ruler_tab(self):
        tab = self.tabs["费用尺"]
        self._entry_row(tab, 0, "WebSocket 地址", "ruler.websocket_uri", width=36)
        self._entry_row(tab, 1, "重连间隔", "ruler.reconnect_delay", note="1 至 60 秒")
        ttk.Label(tab, text="修改后需重启打轴器生效。", style="Settings.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(14, 0)
        )

    def _build_auto_pause_tab(self):
        tab = self.tabs["自动暂停"]
        self._entry_row(
            tab, 0, "PC 暂停键保持时间", "auto_pause.pc_key_hold_ms",
            note="10 至 500 毫秒；即 ESC 按下到松开的间隔",
        )
        self._check_row(tab, 1, "发送暂停前将游戏窗口切到前台", "auto_pause.focus_game_before_send")
        self._check_row(tab, 2, "绑定 PC 游戏窗口时检查管理员权限", "auto_pause.require_admin_for_pc")

    def _build_emulator_tab(self):
        tab = self.tabs["模拟器"]
        self._check_row(tab, 0, "启用模拟器 ADB 自动暂停", "emulator.enabled")
        self._check_row(tab, 1, "自动探测模拟器和 ADB", "emulator.auto_detect")
        self._check_row(tab, 2, "绑定模拟器窗口时优先使用 ADB", "emulator.prefer_for_emulator")

        ttk.Label(tab, text="模拟器安装目录", style="Settings.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(tab, textvariable=self._variable("emulator.install_dir")).grid(row=3, column=1, sticky="ew", padx=10)
        ttk.Button(tab, text="浏览…", command=self._browse_emulator_dir).grid(row=3, column=2)

        ttk.Label(tab, text="ADB 程序路径", style="Settings.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(tab, textvariable=self._variable("emulator.adb_path")).grid(row=4, column=1, sticky="ew", padx=10)
        ttk.Button(tab, text="浏览…", command=self._browse_adb).grid(row=4, column=2)

        ttk.Label(tab, text="ADB 设备", style="Settings.TLabel").grid(row=5, column=0, sticky="w", pady=6)
        self.device_combo = ttk.Combobox(tab, textvariable=self._variable("emulator.serial"), state="readonly")
        self.device_combo.grid(row=5, column=1, sticky="ew", padx=10)

        actions = ttk.Frame(tab, style="Settings.TFrame")
        actions.grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 0))
        self.detect_button = ttk.Button(actions, text="重新探测", command=self._detect_adb)
        self.detect_button.pack(side="left", padx=(0, 6))
        self.refresh_devices_button = ttk.Button(actions, text="刷新设备", command=self._refresh_devices)
        self.refresh_devices_button.pack(side="left", padx=6)
        self.test_adb_button = ttk.Button(actions, text="测试连接", command=self._test_adb)
        self.test_adb_button.pack(side="left", padx=6)
        tab.columnconfigure(1, weight=1)

    def _browse_emulator_dir(self):
        selected = filedialog.askdirectory(parent=self.window, title="选择模拟器安装目录")
        if selected:
            self.variables["emulator.install_dir"].set(selected)

    def _browse_adb(self):
        selected = filedialog.askopenfilename(
            parent=self.window, title="选择 adb 程序", filetypes=[("ADB", "adb.exe"), ("所有文件", "*.*")]
        )
        if selected:
            self.variables["emulator.adb_path"].set(selected)

    def _detect_adb(self):
        directory = self.variables["emulator.install_dir"].get().strip()
        result = detect_adb(candidate_adb_paths(user_dir=directory or None))
        if result.adb_path:
            self.variables["emulator.adb_path"].set(result.adb_path)
        self._set_devices(result.devices, result.selected_serial)
        if not result.adb_path:
            self.error_label.config(text="未找到可用的 ADB，请指定模拟器目录或 ADB 路径。")

    def _set_devices(self, devices, selected=None):
        self.device_combo.configure(values=list(devices))
        if selected:
            self.variables["emulator.serial"].set(selected)
        elif len(devices) != 1:
            self.variables["emulator.serial"].set("")
        elif devices:
            self.variables["emulator.serial"].set(devices[0])

    def _refresh_devices(self):
        adb_path = self.variables["emulator.adb_path"].get().strip()
        devices = adb_devices(adb_path) if adb_path else []
        current = self.variables["emulator.serial"].get().strip()
        self._set_devices(devices, current if current in devices else None)

    def _test_adb(self):
        adb_path = self.variables["emulator.adb_path"].get().strip()
        devices = adb_devices(adb_path) if adb_path else []
        if devices:
            messagebox.showinfo("ADB 连接", f"连接正常，发现 {len(devices)} 台设备。", parent=self.window)
        else:
            messagebox.showwarning("ADB 连接", "未发现在线设备，请启动模拟器并开启 ADB。", parent=self.window)

    def _collect(self):
        data = copy.deepcopy(self.original)
        for path, variable in self.variables.items():
            set_setting(data, path, variable.get())
        return validate_settings(data)

    def _restore_defaults(self):
        defaults = default_settings()
        for path, variable in self.variables.items():
            variable.set(get_setting(defaults, path))
        self._shortcut_capture_path = None
        self._shortcut_capture_original = None
        for action in DEFAULT_SHORTCUTS:
            path = f"shortcuts.{action}"
            self.shortcut_display_vars[path].set(display_sequence(self.variables[path].get()))
        self.error_label.config(text="")

    def _cancel(self):
        self.window.destroy()

    def _save(self):
        try:
            settings = self._collect()
        except SettingsValidationError as exc:
            self.error_label.config(text=str(exc))
            return
        restart_required = settings["ruler"] != self.original["ruler"]
        self.on_save(settings, restart_required)
        self.window.destroy()
