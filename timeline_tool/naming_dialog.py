import tkinter as tk
from tkinter import ttk, messagebox


class NamingDialog(tk.Toplevel):
    """保存时的规范化命名填写对话框，支持多预设切换。"""

    def __init__(self, parent, presets, default_preset, track_count, result_callback):
        super().__init__(parent)
        self.title("保存 - 填写信息")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._presets = presets
        self._default_preset = default_preset
        self._track_count = track_count
        self._result_callback = result_callback
        self._entries = {}
        self._current_preset = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # 居中显示（在 UI 构建完成后计算动态高度）
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w = 420
        h = self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _build_ui(self):
        pad = 10

        # --- 顶部预设导航栏 ---
        nav_frame = ttk.Frame(self)
        nav_frame.pack(fill=tk.X, padx=pad, pady=(pad, 4))

        self._preset_buttons = {}
        for preset in self._presets:
            name = preset["name"]
            btn = ttk.Button(
                nav_frame,
                text=name,
                command=lambda n=name: self._switch_preset(n),
                width=8
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self._preset_buttons[name] = btn

        # --- 表单容器 ---
        self._form_container = ttk.Frame(self)
        self._form_container.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(4, 4))

        # --- 按钮区 ---
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=pad, pady=(0, pad))

        ttk.Button(btn_frame, text="取消", command=self._on_cancel).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="确认保存", command=self._on_confirm).pack(side=tk.RIGHT, padx=4)

        # 默认选中第一个匹配的 preset
        target = self._default_preset if self._default_preset else (
            self._presets[0]["name"] if self._presets else None
        )
        if target and target in self._preset_buttons:
            self._switch_preset(target)
        elif self._presets:
            self._switch_preset(self._presets[0]["name"])

    def _switch_preset(self, preset_name):
        """切换到指定预设，重建表单。"""
        self._current_preset = preset_name

        # 更新按钮外观：当前选中设为 outline，其他恢复默认
        for name, btn in self._preset_buttons.items():
            if name == preset_name:
                btn.configure(bootstyle="outline")
            else:
                btn.configure(bootstyle="default")

        # 清空旧表单
        for widget in self._form_container.winfo_children():
            widget.destroy()
        self._entries.clear()

        # 找到对应 preset 的 fields
        fields = []
        for p in self._presets:
            if p.get("name") == preset_name:
                fields = p.get("fields", [])
                break

        # 重建表单
        for field in fields:
            row = ttk.Frame(self._form_container)
            row.pack(fill=tk.X, pady=5)

            label_text = field["label"]
            hint = field.get("hint", "")
            default = field.get("default", "")
            allow_empty = field.get("allow_empty", True)

            lbl = ttk.Label(row, text=f"{label_text}：", font=("Segoe UI", 10))
            lbl.pack(side=tk.LEFT)

            if hint:
                hint_lbl = ttk.Label(row, text=f"({hint})", foreground="#5c6370", font=("Segoe UI", 9))
                hint_lbl.pack(side=tk.LEFT)

            entry = ttk.Entry(row, font=("Segoe UI", 10))
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

            # 设置默认值
            init_val = default
            if init_val == "AUTO_TRACKS":
                init_val = f"{self._track_count}o" if self._track_count > 0 else ""
            elif init_val == "AUTO_TIMESTAMP":
                from datetime import datetime
                init_val = datetime.now().strftime("%m%d%H%M")

            entry.insert(0, init_val)
            self._entries[label_text] = {"entry": entry, "allow_empty": allow_empty}

        # 刷新布局以确保新 widget 正确显示
        self.update_idletasks()

    def _on_confirm(self):
        values = {}
        for label, meta in self._entries.items():
            val = meta["entry"].get().strip()
            if not val and not meta["allow_empty"]:
                messagebox.showwarning("填写不完整", f"「{label}」不允许为空，请填写。", parent=self)
                return
            values[label] = val

        self._result_callback(values)
        self.destroy()

    def _on_cancel(self):
        self._result_callback(None)
        self.destroy()
