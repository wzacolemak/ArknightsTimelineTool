import tkinter as tk
from tkinter import ttk, simpledialog, TclError, messagebox
import ttkbootstrap as ttkb
from ttkbootstrap.constants import *
import queue
import logging
import os
import subprocess
from PIL import Image, ImageTk

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False
    logging.warning("'winsound' 模块未找到，声音提醒功能将不可用。")

import config
from utils import resource_path, format_frame_time
from file_io import load_timeline_from_file, save_timeline_to_file
from websocket_client import WebsocketClient
from timeline_track import TimelineTrack
from naming_manager import NamingManager
from naming_dialog import NamingDialog
from pause_engine import PauseEngine, resolve_lead_frames
from pause_queue import PauseGroup, PendingPauseQueue
from ruler_process import find_ruler_process_ids
from game_window import (
    BoundWindow,
    load_bound,
    save_bound,
    resolve_game_window,
    pick_window_under_cursor,
    refresh_bound_hwnd,
    find_maa_pc_client,
    describe_hwnd,
)
from hotkey_send import is_elevated, send_adb_pause_key, send_pc_pause_key
from adb_input import looks_like_emulator_window

logger = logging.getLogger(__name__)


class SimpleTooltip:
    """轻量级 tooltip，支持智能上下位置切换和文本动态更新。"""

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip = None
        self._after_id = None
        self._bind()

    def set_text(self, text):
        """动态更新提示文本。"""
        self.text = text
        if self._tip:
            self._tip.label.config(text=text)

    def _bind(self):
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)
        self.widget.bind("<ButtonPress>", self._on_leave)

    def _on_enter(self, event=None):
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        self._hide()

    def _show(self):
        if self._tip is None:
            self._tip = tk.Toplevel(self.widget)
            self._tip.overrideredirect(True)
            self._tip.wm_attributes("-topmost", True)
            self._tip.label = tk.Label(
                self._tip,
                text=self.text,
                bg="#ffffff",
                fg="#282c34",
                relief="solid",
                borderwidth=1,
                font=(config.FONT_FAMILY, -14),
                padx=10,
                pady=6,
            )
            self._tip.label.pack()

        self._tip.deiconify()
        self._tip.update_idletasks()

        wx, wy = self.widget.winfo_rootx(), self.widget.winfo_rooty()
        ww, wh = self.widget.winfo_width(), self.widget.winfo_height()
        tw, th = self._tip.label.winfo_reqwidth(), self._tip.label.winfo_reqheight()
        sh = self.widget.winfo_screenheight()

        x = wx + max(0, (ww - tw) // 2)
        # 如果 tooltip 下方会超出屏幕，则显示在 widget 上方
        if wy + wh + th + 10 > sh:
            y = wy - th - 2
        else:
            y = wy + wh + 2

        self._tip.geometry(f"+{x}+{y}")

    def _hide(self):
        if self._tip:
            self._tip.withdraw()


class TimelineApp:
    def __init__(self, root, scaling_factor=1.0, autoload_path=None, open_file=None):
        self.root = root
        self._autoload_path = autoload_path

        # --- 基于缩放比例计算所有UI尺寸 ---
        self.scaling_factor = scaling_factor
        self.global_zoom = 1.0
        self._calculate_scaled_dimensions()

        self._configure_root_window()

        # --- 核心状态 ---
        self.current_game_frame = 0
        self.timeline_offset = 0.0
        self.ops_collapsed = False
        self._ops_width = 0
        self._expanded_width = self.scaled_win_width

        # --- 拖动与动画数据 ---
        self._window_drag_data = {"x": 0, "y": 0}
        self._timeline_drag_data = {"x": 0, "start_x": 0, "is_dragging": False, "last_dx": 0}
        self.is_animating = False
        self.animation_target_frame = 0
        self.is_inertial_scrolling = False
        self.inertia_velocity = 0.0

        # --- 脏标记（未保存修改检测） ---
        self._dirty = False

        # --- 当前打开的文件路径（None 表示未打开任何文件） ---
        self._current_file = None

        # --- 多轨道 ---
        self.tracks = []
        self.active_track_index = 0
        self._mode_trace_id = None
        self.track_buttons = []

        # --- 通信队列与图标 ---
        self.ws_queue = queue.Queue()
        self.icons = {}
        self._load_icons()

        # --- 命名管理器 ---
        self.naming_mgr = NamingManager()

        # --- WebSocket 时间流逝跟踪（用于磁铁吸附锁定） ---
        self._last_game_frame = -1
        self._is_time_flowing = False

        # --- 自动暂停 ---
        self.pause_engine = PauseEngine()
        self._bound_window = load_bound(self._bound_window_path())
        self._pause_status = "暂停: 就绪"
        # None | "verifying" | "frozen"
        # verifying: 刚发键，按费用尺帧确认是否真停
        # frozen: 已确认停表，等用户恢复后再允许下一次
        self._pause_gate = None
        self._pause_gate_frame = -1
        self._pause_verify = None  # dict: method_used/start_frame/stall_*/...
        self._pending_pause_groups = PendingPauseQueue()
        self._active_pause_group = None
        self._admin_warned = False
        self._duplicate_ruler_warned = False
        self._is_admin = is_elevated()
        # 暂停提前帧（全局，操作面板 Spinbox；持久化 pause_settings.json）
        self.pause_lead_var = tk.StringVar()
        self._load_pause_settings()
        if not self._is_admin:
            logger.warning(
                "当前未以管理员运行：绑定 PC 客户端时自动暂停可能无效，"
                "请右键 TimelineTool.exe → 以管理员身份运行"
            )
        if self._bound_window:
            logger.info(
                "已加载绑定窗: title=%r class=%r hwnd=%s",
                self._bound_window.title,
                self._bound_window.class_name,
                self._bound_window.hwnd,
            )

        # --- 窗口最小化（无边框 HUD） ---
        self._minimized = False
        self._restore_geometry = None
        self._normal_alpha = config.DEFAULT_ALPHA

        # --- UI设置与启动 ---
        self._setup_styles()
        self._setup_ui()
        self._setup_keybindings()
        # 空白区域拖窗：bind_all + 命中过滤（ttk 空白区往往收不到自身绑定）
        self._window_dragging = False
        self.root.bind_all("<ButtonPress-1>", self._on_global_window_press, add="+")
        self.root.bind_all("<B1-Motion>", self._on_global_window_motion, add="+")
        self.root.bind_all("<ButtonRelease-1>", self._on_global_window_release, add="+")

        if open_file and os.path.exists(open_file):
            # 重启后重新打开原文件
            self._load_file(open_file)
        elif autoload_path:
            # 兼容旧版：从临时文件自动加载（保留功能但不再主动使用）
            self._do_autoload(autoload_path)
        else:
            # 默认创建一个轨道
            self.add_track()

        # --- 启动后台服务与UI更新循环 ---
        self.ws_client = WebsocketClient(config.WEBSOCKET_URI)
        self.ws_client.start(self.ws_queue)
        self.root.after(config.QUEUE_POLL_INTERVAL, self._process_ws_queue)
        self.root.after(800, self._check_duplicate_rulers)
        logger.info(f"TimelineApp {config.VERSION} 初始化完成。")

    def _calculate_scaled_dimensions(self):
        """根据缩放因子计算所有UI元素的尺寸。"""
        sf = self.scaling_factor
        # 窗口与图标
        self.scaled_win_width = int(config.WINDOW_WIDTH * sf)
        self.scaled_win_height = int(config.WINDOW_HEIGHT * sf)
        self.scaled_icon_size = (int(config.ICON_SIZE[0] * sf), int(config.ICON_SIZE[1] * sf))

        # 时间轴与节点尺寸
        self.scaled_pixels_per_frame = config.PIXELS_PER_FRAME * sf * self.global_zoom
        self.scaled_node_diamond_h = int(config.NODE_DIAMOND_SIZE["h"] * sf)
        self.scaled_node_diamond_w = int(config.NODE_DIAMOND_SIZE["w"] * sf)
        self.scaled_track_height = int(config.TIMELINE_TRACK_HEIGHT * sf)
        self.scaled_major_tick_h = int(config.TIMELINE_MAJOR_TICK_H * sf)
        self.scaled_minor_tick_h = int(config.TIMELINE_MINOR_TICK_H * sf)

        # 字体
        self.scaled_font_normal = int(config.FONT_SIZE_NORMAL * sf)
        self.scaled_font_large = int(config.FONT_SIZE_LARGE * sf)

        # 边距和 UI 绘图细节
        self.scaled_pad_xs = int(config.PADDING_XS * sf)
        self.scaled_pad_s = int(config.PADDING_S * sf)
        self.scaled_pad_m = int(config.PADDING_M * sf)
        self.scaled_pad_l = int(config.PADDING_L * sf)
        self.scaled_pad_xl = int(config.PADDING_XL * sf)

        self.scaled_time_label_offset = int(config.TIMELINE_TIME_LABEL_OFFSET_Y * sf)
        self.scaled_node_name_offset = int(config.NODE_NAME_LABEL_OFFSET_Y * sf)
        self.scaled_playhead_h = int(config.PLAYHEAD_TRIANGLE_HEIGHT * sf)
        self.scaled_playhead_w = int(config.PLAYHEAD_TRIANGLE_WIDTH * sf)
        self.scaled_cursor_wing = int(config.CENTER_CURSOR_WING_LENGTH * sf)
        self.scaled_drag_threshold = int(config.DRAG_START_THRESHOLD * sf)

        self.scaled_bottom_handle_height = max(10, int(10 * sf))
        self.scaled_right_handle_width = max(8, int(8 * sf))

    def _configure_root_window(self):
        """配置根窗口的基本属性。"""
        self.root.title(f"明日方舟打轴/对轴器 {config.VERSION}")
        self.root.geometry(f"{self.scaled_win_width}x{self.scaled_win_height}+100+100")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", config.DEFAULT_ALPHA)

    def _load_icons(self):
        """加载所有需要的图标文件。"""
        icon_files = {
            "open": "open.png",
            "save": "save.png",
            "magnet_on": "magnet_on.png",
            "magnet_off": "magnet_off.png",
            "add": "add.png",
            "remove": "remove.png",
            "color": "color.png",
            "sound_on": "sound_on.png",
            "sound_off": "sound_off.png",
            "visual_on": "visual_on.png",
            "visual_off": "visual_off.png",
            "rename": "rename.png",
            "restart": "start.png",
            "pause_on": "pause_on.png",
            "pause_off": "pause_off.png",
        }
        for name, filename in icon_files.items():
            path = resource_path(os.path.join(config.ICON_DIR, filename))
            try:
                img = Image.open(path).resize(self.scaled_icon_size, Image.Resampling.LANCZOS)
                self.icons[name] = ImageTk.PhotoImage(img)
            except FileNotFoundError:
                self.icons[name] = None
                logger.error(f"图标文件未找到: {path}")

    def _setup_styles(self):
        """设置应用程序的ttkbootstrap样式。"""
        style = ttkb.Style.get_instance()
        style.configure("TFrame", background="#282c34")
        style.configure("TLabel", background="#282c34", foreground="#abb2bf")
        style.configure("Tool.TButton", background="#282c34", borderwidth=0, focuscolor="#282c34",
                        padding=config.TOOL_BUTTON_PADDING)
        style.map("Tool.TButton", background=[("active", "#3e4451")])
        style.configure("Info.TLabel", font=(config.FONT_FAMILY, self.scaled_font_normal))
        style.configure("Now.Info.TLabel", foreground="cyan")

    def _setup_ui(self):
        """创建应用程序的主要用户界面。"""
        main_frame = ttk.Frame(self.root, style="TFrame")
        main_frame.pack(expand=True, fill=BOTH)

        # --- 顶部轨道选择栏 ---
        self.track_selector_frame = ttk.Frame(main_frame, style="TFrame")
        # 顶栏整体标记为可拖区域（子按钮仍通过 class 拦截）
        self.track_selector_frame._hud_drag_zone = True

        self.add_track_btn = ttk.Button(self.track_selector_frame, text="新建轨道", command=self._add_new_track,
                                        style="Tool.TButton")
        self.add_track_btn.pack(side=LEFT, padx=self.scaled_pad_s)
        self.remove_track_btn = ttk.Button(self.track_selector_frame, text="删除轨道",
                                           command=self._remove_active_track, style="Tool.TButton")
        self.remove_track_btn.pack(side=LEFT, padx=self.scaled_pad_s)

        # 中间可扩展区：轨道页签 + 右侧空白拖条（ttk 空白常点不到，用 tk.Frame）
        self.track_buttons_frame = ttk.Frame(self.track_selector_frame, style="TFrame")
        self.track_buttons_frame.pack(side=LEFT, fill=X, expand=True, padx=self.scaled_pad_m)
        self.track_buttons_frame._hud_drag_zone = True
        self._top_drag_filler = tk.Frame(
            self.track_buttons_frame, bg="#282c34", cursor="fleur", height=1
        )
        self._top_drag_filler._hud_drag_zone = True
        self._top_drag_filler.pack(side=RIGHT, fill=BOTH, expand=True)

        # 关闭按钮：与工具栏同色，仅悬停略亮（避免 Danger 常亮红）
        close_btn = ttk.Button(
            self.track_selector_frame,
            text="✕",
            command=self._on_close_request,
            style="Tool.TButton",
            width=2,
        )
        close_btn.pack(side=RIGHT, padx=(self.scaled_pad_s, 0))
        SimpleTooltip(close_btn, text="关闭")

        # 最小化：收成细条，只留恢复/关闭
        min_btn = ttk.Button(
            self.track_selector_frame,
            text="—",
            command=self._minimize_window,
            style="Tool.TButton",
            width=2,
        )
        min_btn.pack(side=RIGHT, padx=self.scaled_pad_s)
        SimpleTooltip(min_btn, text="最小化")

        # 重启按钮
        restart_icon = self.icons.get("restart")
        restart_btn = ttk.Button(self.track_selector_frame, command=self._restart_app, style="Tool.TButton")
        if restart_icon:
            restart_btn.config(image=restart_icon)
            SimpleTooltip(restart_btn, text="重启")
        else:
            restart_btn.config(text="↻")
            SimpleTooltip(restart_btn, text="重启")
        restart_btn.pack(side=RIGHT, padx=self.scaled_pad_s)

        # 折叠/展开左侧操作面板
        self.collapse_btn = ttk.Button(self.track_selector_frame, text="◀", command=self._toggle_ops_panel,
                                       style="Tool.TButton", width=2)
        self.collapse_btn.pack(side=RIGHT, padx=self.scaled_pad_s)
        self.collapse_btn._tooltip = SimpleTooltip(self.collapse_btn, text="隐藏操作面板")

        # 打开/保存：针对整份轴文件，放顶栏右侧（折叠按钮左侧）
        open_icon = self.icons.get("open")
        save_icon = self.icons.get("save")
        self.top_open_btn = ttk.Button(
            self.track_selector_frame, command=self._load_timeline, style="Tool.TButton"
        )
        if open_icon:
            self.top_open_btn.config(image=open_icon)
        else:
            self.top_open_btn.config(text="打开")
        SimpleTooltip(self.top_open_btn, text="打开时间轴文件")
        self.top_open_btn.pack(side=RIGHT, padx=self.scaled_pad_s)

        self.top_save_btn = ttk.Button(
            self.track_selector_frame, command=self._save_timeline, style="Tool.TButton"
        )
        if save_icon:
            self.top_save_btn.config(image=save_icon)
        else:
            self.top_save_btn.config(text="保存")
        SimpleTooltip(self.top_save_btn, text="保存时间轴文件")
        self.top_save_btn.pack(side=RIGHT, padx=self.scaled_pad_s)

        # --- 底部 resize handle（双横线，只调高度，禁止拖窗） ---
        # 注意：必须在 content_frame 之前 pack，否则 expand=True 的 content_frame
        # 会抢占全部剩余空间，导致 bottom_resize_handle 被挤出可视区域。
        self.bottom_resize_handle = tk.Frame(main_frame, bg="#3e4451", cursor="sb_v_double_arrow",
                                             height=self.scaled_bottom_handle_height)
        self.bottom_resize_handle.pack_propagate(False)
        self.bottom_resize_handle._no_hud_drag = True
        bottom_label = tk.Label(self.bottom_resize_handle, text="━━", bg="#3e4451", fg="#5c6370",
                                font=(config.FONT_FAMILY, self.scaled_font_normal))
        bottom_label._no_hud_drag = True
        bottom_label.pack(expand=True)
        for w in (self.bottom_resize_handle, bottom_label):
            w.bind("<ButtonPress-1>", self._on_resize_height_start)
            w.bind("<B1-Motion>", self._on_resize_height_motion)
            w.bind("<ButtonRelease-1>", lambda e: setattr(self, "_window_dragging", False))

        # --- 内容区域（左 ops + 右 tracks） ---
        content_frame = ttk.Frame(main_frame, style="TFrame")

        self.ops_frame = ttk.Frame(content_frame, width=self.scaled_win_width // 3, style="TFrame")
        self.ops_frame.pack(side=LEFT, fill=Y, padx=self.scaled_pad_m, pady=self.scaled_pad_m)
        self.ops_frame.pack_propagate(False)
        self.dynamic_ops_frame = ttk.Frame(self.ops_frame, style="TFrame")
        self.dynamic_ops_frame.pack(side=TOP, fill=BOTH, expand=True)
        self.dynamic_ops_frame.columnconfigure((0, 1, 2), weight=1)

        # 轨道区域容器
        self.tracks_grip_frame = ttk.Frame(content_frame, style="TFrame")
        self.tracks_grip_frame.pack(side=LEFT, fill=BOTH, expand=True)

        self.tracks_container = ttk.Frame(self.tracks_grip_frame, style="TFrame")
        self.tracks_container.pack(side=TOP, fill=BOTH, expand=True, padx=self.scaled_pad_m, pady=(self.scaled_pad_m, 0))

        # --- 右侧 resize handle（双竖线，调宽度） ---
        self.right_resize_handle = tk.Frame(content_frame, bg="#3e4451", cursor="sb_h_double_arrow",
                                            width=self.scaled_right_handle_width)
        self.right_resize_handle.pack_propagate(False)
        self.right_resize_handle._no_hud_drag = True
        right_label = tk.Label(self.right_resize_handle, text="┃┃", bg="#3e4451", fg="#5c6370",
                               font=(config.FONT_FAMILY, self.scaled_font_normal))
        right_label._no_hud_drag = True
        right_label.pack(expand=True)
        self.right_resize_handle.pack(side=RIGHT, fill=Y, padx=(0, self.scaled_pad_m), pady=self.scaled_pad_m)
        for w in (self.right_resize_handle, right_label):
            w.bind("<ButtonPress-1>", self._on_resize_width_start)
            w.bind("<B1-Motion>", self._on_resize_width_motion)
            w.bind("<ButtonRelease-1>", lambda e: setattr(self, "_window_dragging", False))

        # 主内容容器（最小化时整块隐藏）
        self._main_frame = main_frame
        self._content_frame = content_frame

        # 最小化细条（默认不显示）
        self._mini_bar = ttk.Frame(self.root, style="TFrame")
        self._mini_bar._hud_drag_zone = True
        mini_label = ttk.Label(
            self._mini_bar,
            text="打轴器",
            style="Info.TLabel",
            cursor="fleur",
        )
        mini_label.pack(side=LEFT, padx=self.scaled_pad_m)
        mini_label._hud_drag_zone = True
        for w in (self._mini_bar, mini_label):
            w.bind("<Double-Button-1>", lambda e: self._restore_window())
        ttk.Button(
            self._mini_bar,
            text="▢",
            command=self._restore_window,
            style="Tool.TButton",
            width=2,
        ).pack(side=RIGHT, padx=self.scaled_pad_s)
        ttk.Button(
            self._mini_bar,
            text="✕",
            command=self._on_close_request,
            style="Tool.TButton",
            width=2,
        ).pack(side=RIGHT, padx=self.scaled_pad_s)

        # pack 顺序：先顶部栏 → 再底部把手 → 最后内容区（expand 填满中间剩余空间）
        self.track_selector_frame.pack(side=TOP, fill=X, padx=self.scaled_pad_m, pady=self.scaled_pad_m)
        self.bottom_resize_handle.pack(side=BOTTOM, fill=X, padx=self.scaled_pad_m, pady=(0, self.scaled_pad_m))
        content_frame.pack(side=TOP, fill=BOTH, expand=True)

        # 自动暂停：绑定游戏窗 + 状态
        pause_bar = ttk.Frame(self.ops_frame, style="TFrame")
        pause_bar.pack(side=BOTTOM, fill=X, pady=self.scaled_pad_s)
        ttk.Button(
            pause_bar,
            text="绑定游戏窗",
            command=self._bind_game_window_click,
            style="Tool.TButton",
        ).pack(side=LEFT, fill=X, expand=True, padx=self.scaled_pad_s)
        self.pause_status_label = ttk.Label(
            pause_bar, text=self._pause_status, style="Info.TLabel"
        )
        self.pause_status_label.pack(side=LEFT, padx=self.scaled_pad_s)

        # 全部打轴/对轴（多轨道时显示，位于模式切换上方）
        # pack(side=BOTTOM) 先 pack 的 widget 在更下方，所以 quit_button 先 pack 会位于底部，
        # all_mode_frame 后 pack 会位于 quit_button 上方。
        self.all_mode_frame = ttk.Frame(self.ops_frame, style="TFrame")
        self.all_mode_frame.pack(side=BOTTOM, fill=X, pady=self.scaled_pad_m)
        ttk.Button(self.all_mode_frame, text="全部打轴", command=self._set_all_tracks_mode_editing,
                   style="Tool.TButton").pack(side=LEFT, fill=X, expand=True, padx=self.scaled_pad_s)
        ttk.Button(self.all_mode_frame, text="全部对轴", command=self._set_all_tracks_mode_following,
                   style="Tool.TButton").pack(side=LEFT, fill=X, expand=True, padx=self.scaled_pad_s)

    def _refresh_all_mode_visibility(self):
        """根据轨道数量控制全部打轴/对轴按钮的显示。"""
        if len(self.tracks) > 1:
            self.all_mode_frame.pack_forget()
            self.all_mode_frame.pack(side=BOTTOM, fill=X, pady=self.scaled_pad_m)
        else:
            self.all_mode_frame.pack_forget()

    # ------------------------------------------------------------------
    # Track management
    # ------------------------------------------------------------------
    def add_track(self, track_data=None):
        default_name = f"轨道{len(self.tracks)}"
        track = TimelineTrack(self.tracks_container, self, track_data, default_name=default_name)
        self.tracks.append(track)
        # 新轨道默认开磁铁：蓝线跟着费用尺；可关磁铁后拖动，点「回正」再跟上
        if track_data is None:
            track.magnet_mode.set(True)
        self.set_active_track(track)
        self._refresh_track_selector()
        self._adjust_window_height()
        self._refresh_all_mode_visibility()
        self._update_display()
        if track_data is None:
            self._mark_dirty()

    def _add_new_track(self):
        self.add_track()

    def _remove_active_track(self):
        if not self.tracks:
            return
        if len(self.tracks) <= 1:
            logger.warning("至少保留一个时间轴。")
            return
        track = self.tracks[self.active_track_index]
        track.frame.destroy()
        self.tracks.remove(track)
        self.active_track_index = max(0, self.active_track_index - 1)
        self.set_active_track(self.tracks[self.active_track_index])
        self._refresh_track_selector()
        self._adjust_window_height()
        self._refresh_all_mode_visibility()
        self._update_display()
        self._mark_dirty()

    def _set_all_tracks_mode_editing(self):
        for track in self.tracks:
            track.mode.set("打轴模式")
            # 打轴模式不改变吸附状态，保持用户手动设置
        self._update_ui_for_mode()
        self._update_display()
        logger.info("所有轨道已切换为打轴模式。")

    def _set_all_tracks_mode_following(self):
        for track in self.tracks:
            track.mode.set("对轴模式")
            track.magnet_mode.set(True)  # 全部对轴时强制开启吸附
        self._update_ui_for_mode()
        self._update_display()
        logger.info("所有轨道已切换为对轴模式并强制吸附。")

    def set_active_track(self, track):
        if self._mode_trace_id:
            try:
                self.tracks[self.active_track_index].mode.trace_remove("write", self._mode_trace_id)
            except (tk.TclError, IndexError):
                pass
        self.active_track_index = self.tracks.index(track)
        self._mode_trace_id = track.mode.trace_add("write", self._update_ui_for_mode)
        self._update_ui_for_mode()

        # 视觉反馈：高亮名称
        for t in self.tracks:
            t.name_label.config(foreground="#abb2bf")
        track.name_label.config(foreground="cyan")

        # 更新选择器按钮高亮
        for idx, btn in enumerate(self.track_buttons):
            if idx == self.active_track_index:
                btn.config(style="Outline.TButton")
            else:
                btn.config(style="Tool.TButton")

    def _refresh_track_selector(self):
        for widget in self.track_buttons_frame.winfo_children():
            # 保留右侧空白拖条
            if widget is getattr(self, "_top_drag_filler", None):
                continue
            widget.destroy()
        self.track_buttons = []
        for idx, track in enumerate(self.tracks):
            btn = ttk.Button(self.track_buttons_frame, text=track.name,
                             command=lambda t=track: self.set_active_track(t),
                             style="Tool.TButton")
            # 双击顶栏轨道页签重命名
            btn.bind(
                "<Double-Button-1>",
                lambda e, t=track: t.rename_track_prompt(),
            )
            SimpleTooltip(btn, text="单击切换 · 双击重命名")
            # 页签在拖条左侧
            if getattr(self, "_top_drag_filler", None):
                btn.pack(side=LEFT, padx=self.scaled_pad_s, before=self._top_drag_filler)
            else:
                btn.pack(side=LEFT, padx=self.scaled_pad_s)
            self.track_buttons.append(btn)
        # 重新应用高亮
        if self.tracks and 0 <= self.active_track_index < len(self.tracks):
            self.set_active_track(self.tracks[self.active_track_index])

    def _get_minimum_height(self):
        """计算窗口允许的最小高度（用于限制手动拖拽），保持原始保守值。"""
        selector_h = int(25 * self.scaling_factor)
        bottom_h = self.scaled_bottom_handle_height
        per_track = int(config.TRACK_MIN_HEIGHT * self.scaling_factor)
        ops_min_h = int(80 * self.scaling_factor)
        tracks_h = len(self.tracks) * per_track
        content_h = max(ops_min_h, tracks_h)
        return selector_h + content_h + bottom_h + int(2 * self.scaling_factor)

    def _adjust_window_height(self):
        """根据轨道数量直接调整窗口到合适高度，不依赖最小高度。"""
        selector_h = int(25 * self.scaling_factor)
        bottom_h = self.scaled_bottom_handle_height
        # 每个轨道实际需要约 120px 才能完整显示 title_bar + canvas + info_frame（含充足余量）
        per_track = int(120 * self.scaling_factor)
        tracks_h = len(self.tracks) * per_track
        # 左侧操作面板最小高度，折叠时不计
        ops_min_h = 0 if getattr(self, 'ops_collapsed', False) else int(100 * self.scaling_factor)
        content_h = max(ops_min_h, tracks_h)
        total = selector_h + content_h + bottom_h + int(6 * self.scaling_factor)
        total = max(int(config.MIN_WINDOW_HEIGHT * self.scaling_factor), total)
        self.scaled_win_height = total
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{self.scaled_win_width}x{total}+{x}+{y}")

    def _get_minimum_width(self):
        """计算当前状态允许的最小窗口宽度。折叠时允许更窄。"""
        base = int(config.WINDOW_WIDTH * self.scaling_factor)
        if self.ops_collapsed:
            # 折叠后 ops_frame 消失，最小宽度只需容纳轨道区域 + padding
            return int(base * 2 / 3)
        return base

    def _toggle_ops_panel(self):
        """折叠或展开左侧 ops_frame 操作面板。"""
        if self.ops_collapsed:
            # 展开：恢复 ops_frame，并恢复到折叠前记录的宽度
            self.ops_frame.pack(side=LEFT, fill=Y, padx=self.scaled_pad_m, pady=self.scaled_pad_m,
                                before=self.tracks_grip_frame)
            self.scaled_win_width = self._expanded_width
            self.ops_frame.config(width=self.scaled_win_width // 3)
            self.collapse_btn.config(text="◀")
            self.collapse_btn._tooltip.set_text("隐藏操作面板")
            # 显示新建/删除轨道按钮（使用 before 确保排在 track_buttons_frame 左侧）
            self.add_track_btn.pack(side=LEFT, padx=self.scaled_pad_s, before=self.track_buttons_frame)
            self.remove_track_btn.pack(side=LEFT, padx=self.scaled_pad_s, before=self.track_buttons_frame)
            self.ops_collapsed = False
        else:
            # 折叠：记录当前窗口宽度，然后减去 ops_frame 宽度
            self._expanded_width = self.scaled_win_width
            self._ops_width = self.ops_frame.winfo_width()
            self.ops_frame.pack_forget()
            self.scaled_win_width -= self._ops_width
            self.collapse_btn.config(text="▶")
            self.collapse_btn._tooltip.set_text("展开操作面板")
            # 隐藏新建/删除轨道按钮
            self.add_track_btn.pack_forget()
            self.remove_track_btn.pack_forget()
            self.ops_collapsed = True
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{self.scaled_win_width}x{self.scaled_win_height}+{x}+{y}")
        self._update_display()

    def _distribute_heights(self):
        total_height = self.scaled_win_height
        selector_h = int(25 * self.scaling_factor)
        bottom_h = self.scaled_bottom_handle_height
        # 包含各级 padding 的粗略估计
        padding_estimate = int(4 * self.scaling_factor) + self.scaled_pad_m * 4
        available = total_height - selector_h - bottom_h - padding_estimate
        if len(self.tracks) > 0:
            track_h = max(int(config.TRACK_MIN_HEIGHT * self.scaling_factor), available // len(self.tracks))
        else:
            track_h = available
        for track in self.tracks:
            track.set_height(track_h)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def _check_duplicate_rulers(self) -> None:
        """周期检测费用尺多开，避免旧实例独占 2606 导致时间轴不跟随。"""
        try:
            pids = find_ruler_process_ids()
            if len(pids) > 1:
                self._set_pause_status(f"费用尺多开: {len(pids)} 个进程")
                if not self._duplicate_ruler_warned:
                    self._duplicate_ruler_warned = True
                    logger.warning(
                        "检测到费用尺多开 pids=%s；旧实例可能独占 127.0.0.1:2606，"
                        "导致打轴器连接错误且时间轴不跟随",
                        pids,
                    )
                    messagebox.showwarning(
                        "检测到费用尺多开",
                        "检测到多个 ruler-app.exe 进程：\n\n"
                        f"PID: {', '.join(str(pid) for pid in pids)}\n\n"
                        "旧的或无响应的费用尺可能占用 127.0.0.1:2606，\n"
                        "导致打轴器连接到错误实例、时间轴不跟随。\n\n"
                        "请关闭所有费用尺，再只启动一个费用尺。",
                    )
            else:
                self._duplicate_ruler_warned = False
        except Exception as e:  # noqa: BLE001
            logger.debug("检测费用尺多开失败: %s", e)
        finally:
            try:
                interval = int(
                    getattr(config, "RULER_PROCESS_CHECK_INTERVAL_MS", 5000)
                )
                self.root.after(max(1000, interval), self._check_duplicate_rulers)
            except Exception:  # noqa: BLE001
                pass

    def _process_ws_queue(self):
        """处理来自WebSocket的消息队列并更新UI。"""
        try:
            while not self.ws_queue.empty():
                data = self.ws_queue.get_nowait()
                # API v2 仍推顶层快照；兼容误包一层 payload 的情况
                if isinstance(data, dict) and data.get("type") == "snapshot" and "payload" in data:
                    data = data["payload"]
                is_running = data.get("isRunning", False)
                if is_running:
                    self.current_game_frame = data.get("totalElapsedFrames", self.current_game_frame)

                # 基于费用尺时间是否流逝来控制磁铁吸附锁定
                if is_running:
                    current_frame = data.get("totalElapsedFrames", self.current_game_frame)
                    self.current_game_frame = current_frame

                    # 自动暂停：帧前进时做边沿检测（内部会更新暂停门闩）
                    try:
                        self._maybe_auto_pause(current_frame, is_running=True)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("自动暂停处理异常: %s", e)

                    if current_frame > self._last_game_frame:
                        # 时间正在流逝：对轴轨道强制吸附并锁定
                        self._is_time_flowing = True
                        for track in self.tracks:
                            if track.mode.get() == "对轴模式":
                                if not track.magnet_mode.get():
                                    logger.info(f"[{track.name}] 时间流逝中，强制恢复磁铁吸附。")
                                    track.magnet_mode.set(True)
                                track.magnet_locked = True
                                track._magnet_unlock_log_done = False
                    elif current_frame == self._last_game_frame:
                        # 时间暂停了（isRunning=True 但帧数没增加）
                        self._is_time_flowing = False
                        # 门闩推进的单一入口是 _maybe_auto_pause（上面已在本轮调过
                        # _update_pause_gate(current_frame)）。此处不再二次调用，
                        # 否则同一份停帧快照会把 verifying 的 stall_count 双计，
                        # 把单帧抖动误判为已稳定停表（final-review I1）。
                        for track in self.tracks:
                            if getattr(track, 'magnet_locked', False):
                                track.magnet_locked = False
                                if not getattr(track, '_magnet_unlock_log_done', False):
                                    logger.info(f"[{track.name}] 时间暂停，解除磁铁吸附锁定。")
                                    track._magnet_unlock_log_done = True

                    self._last_game_frame = current_frame
                else:
                    # 尺子未运行：解除锁定；若在校验，视为已停表
                    self._is_time_flowing = False
                    if self._pause_gate == "verifying":
                        self._mark_pause_verified(self.current_game_frame, "isRunning=false")
                    elif self._pause_gate == "frozen":
                        # 保持 frozen，等 isRunning 再 True 且帧前进后解锁
                        pass
                    for track in self.tracks:
                        if getattr(track, 'magnet_locked', False):
                            track.magnet_locked = False
                            if not getattr(track, '_magnet_unlock_log_done', False):
                                logger.info(f"[{track.name}] 时间暂停，解除磁铁吸附锁定。")
                                track._magnet_unlock_log_done = True
                    self._last_game_frame = -1

            if self.is_animating:
                distance = self.animation_target_frame - self.timeline_offset
                if abs(distance) < 0.5:
                    self.timeline_offset = self.animation_target_frame
                    self.is_animating = False
                else:
                    self.timeline_offset += distance * 0.2
            elif self.is_inertial_scrolling:
                self.timeline_offset -= self.inertia_velocity
                self.inertia_velocity *= config.INERTIA_FRICTION
                if abs(self.inertia_velocity) < 0.1:
                    self.is_inertial_scrolling = False
                    self.inertia_velocity = 0

            self._update_display()
        except queue.Empty:
            pass
        finally:
            self.root.after(config.QUEUE_POLL_INTERVAL, self._process_ws_queue)

    # ------------------------------------------------------------------
    # 自动暂停
    # ------------------------------------------------------------------
    def _app_data_dir(self) -> str:
        """配置/绑定文件目录：开发模式项目根，打包则 exe 同级。"""
        import sys

        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return (
            os.path.dirname(script_dir)
            if os.path.basename(script_dir) == "timeline_tool"
            else script_dir
        )

    def _bound_window_path(self) -> str:
        return os.path.join(self._app_data_dir(), config.BOUND_WINDOW_FILE)

    def _pause_settings_path(self) -> str:
        name = getattr(config, "PAUSE_SETTINGS_FILE", "pause_settings.json")
        return os.path.join(self._app_data_dir(), name)

    def _load_pause_settings(self) -> None:
        """加载 pause_settings.json；缺省用 config.PAUSE_LEAD_FRAMES。"""
        import json

        default_lead = getattr(config, "PAUSE_LEAD_FRAMES", 1)
        if default_lead is None:
            default_lead = resolve_lead_frames(
                lead_frames=None,
                lead_ms=getattr(config, "PAUSE_LEAD_MS", 0),
                logic_fps=getattr(config, "LOGIC_FPS", getattr(config, "FPS", 30)),
            )
        lead = int(default_lead or 0)
        path = self._pause_settings_path()
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "pause_lead_frames" in data:
                    lead = max(0, int(data["pause_lead_frames"]))
        except Exception as e:  # noqa: BLE001
            logger.warning("读取暂停设置失败: %s", e)
        self.pause_lead_var.set(str(lead))
        try:
            self.pause_lead_var.trace_add("write", self._on_pause_lead_changed)
        except Exception:  # noqa: BLE001
            pass

    def _save_pause_settings(self) -> None:
        import json

        path = self._pause_settings_path()
        try:
            lead = self._get_pause_lead_frames()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"pause_lead_frames": lead}, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning("保存暂停设置失败: %s", e)

    def _get_pause_lead_frames(self) -> int:
        """UI 优先；解析失败回退 config。"""
        try:
            raw = (self.pause_lead_var.get() or "").strip()
            if raw != "":
                return max(0, int(raw))
        except (TypeError, ValueError, TclError):
            pass
        return resolve_lead_frames(
            lead_frames=getattr(config, "PAUSE_LEAD_FRAMES", 0),
            lead_ms=getattr(config, "PAUSE_LEAD_MS", 0),
            logic_fps=getattr(config, "LOGIC_FPS", getattr(config, "FPS", 30)),
        )

    def _on_pause_lead_changed(self, *_args) -> None:
        try:
            lead = self._get_pause_lead_frames()
            self._save_pause_settings()
            self._set_pause_status(f"暂停提前: {lead} 帧")
        except Exception:  # noqa: BLE001
            pass

    def _set_pause_status(self, text: str) -> None:
        self._pause_status = text
        label = getattr(self, "pause_status_label", None)
        if label is not None:
            try:
                label.config(text=text)
            except TclError:
                pass

    def _resolve_live_game_window(self):
        """
        发键前解析活窗（对齐 MAA 每次用当前 hwnd）：
          1) 刷新绑定（title+class 重枚举，丢弃过期 hwnd）
          2) 回退 resolve_game_window / 精确标题「明日方舟」
        若绑定 hwnd 变了会自动写回 bound_game_window.json。
        """
        bound = self._bound_window
        win = None
        if bound and (bound.title or bound.class_name or bound.hwnd):
            updated, win = refresh_bound_hwnd(bound)
            if win and updated.hwnd != (bound.hwnd or 0):
                logger.info(
                    "绑定窗 hwnd 已刷新: %s → %s title=%r class=%r",
                    bound.hwnd,
                    updated.hwnd,
                    updated.title,
                    updated.class_name,
                )
                self._bound_window = updated
                try:
                    save_bound(self._bound_window_path(), updated)
                except Exception as e:  # noqa: BLE001
                    logger.warning("写回绑定窗失败: %s", e)
            elif win:
                self._bound_window = updated

        if not win:
            win = resolve_game_window(
                getattr(config, "GAME_WINDOW_TITLE_KEYWORDS", []),
                self._bound_window,
            )

        if not win:
            # 最后再试一次 MAA 精确标题（不依赖绑定/关键字）
            win = find_maa_pc_client()

        if win:
            live = describe_hwnd(int(win["hwnd"])) or win
            logger.info(
                "发键目标窗: hwnd=%s title=%r class=%r pid=%s size=%sx%s visible=%s minimized=%s",
                live.get("hwnd"),
                live.get("title"),
                live.get("class_name"),
                live.get("pid"),
                live.get("width"),
                live.get("height"),
                live.get("visible"),
                live.get("minimized"),
            )
            return live
        return None

    # ------------------------------------------------------------------
    # 顺序暂停状态机 helpers
    # ------------------------------------------------------------------
    def _drop_topmost_for_pause(self) -> None:
        try:
            self.root.wm_attributes("-topmost", False)
            self.root.update_idletasks()
        except Exception as e:  # noqa: BLE001
            logger.debug("取消 topmost 失败: %s", e)

    def _restore_topmost_for_pause(self) -> None:
        try:
            self.root.wm_attributes("-topmost", True)
        except Exception as e:  # noqa: BLE001
            logger.debug("恢复 topmost 失败: %s", e)

    def _event_label(self, event) -> str:
        """单事件标签：`[轨道名]节点名@节点帧`，有提前量时追加 `(提前N@触发帧)`。"""
        base = f"[{event.get('track_name', '')}]{event.get('name', '')}@{event.get('frame')}"
        trig = event.get("trigger_frame")
        lf = event.get("lead_frames") or 0
        if lf and trig is not None and trig != event.get("frame"):
            return f"{base}(提前{lf}@{trig})"
        return base

    def _group_summary(self, group: PauseGroup) -> str:
        """一组暂停事件的可读摘要（事件间用 | 连接）。"""
        return " | ".join(self._event_label(ev) for ev in group.events)

    def _queue_pause_events(self, events) -> list:
        """把 PauseEngine 本 tick 返回的事件入队；按新增 group 记录日志。"""
        added = self._pending_pause_groups.add(events)
        for group in added:
            logger.info(
                "暂停节点入队 trigger=%s queue=%d: %s",
                group.trigger_frame,
                len(self._pending_pause_groups),
                self._group_summary(group),
            )
        return added

    def _clear_pause_sequence(self, reason: str) -> None:
        """清空 pending queue、active group、gate、verify，记录原因。"""
        pending = len(self._pending_pause_groups)
        self._pending_pause_groups.clear()
        self._active_pause_group = None
        self._pause_gate = None
        self._pause_verify = None
        self._pause_gate_frame = -1
        logger.info("清空暂停序列 reason=%s pending=%d", reason, pending)

    def _mark_pause_failed(self, current_frame: int, reason: str) -> None:
        """当前 active group 发键/校验失败：记录、清 gate/verify/active；不重试。"""
        v = self._pause_verify if isinstance(self._pause_verify, dict) else None
        method = (v or {}).get("method_used") or ""
        trigger = (v or {}).get("trigger_frame")
        start = (v or {}).get("start_frame")
        summary = (v or {}).get("summary") or ""
        logger.warning(
            "暂停失败 method=%s trigger=%s start=%s current=%s reason=%s summary=%s",
            method,
            trigger,
            start,
            current_frame,
            reason,
            summary,
        )
        self._pause_gate = None
        self._pause_verify = None
        self._active_pause_group = None
        self._set_pause_status(f"暂停失败: {reason}")

    def _mark_pause_verified(self, current_frame: int, reason: str) -> None:
        v = self._pause_verify if isinstance(self._pause_verify, dict) else None
        method = (v or {}).get("method_used") or ""
        trigger = (v or {}).get("trigger_frame")
        start = (v or {}).get("start_frame") if v else None
        latency = ""
        if trigger is not None and current_frame >= int(trigger):
            latency = f" 延迟{current_frame - int(trigger)}帧"
        self._pause_gate = "frozen"
        self._pause_gate_frame = current_frame
        self._pause_verify = None
        # active group 保留，直到用户恢复时由 _update_pause_gate(frozen 分支) 清空
        self._set_pause_status(f"已暂停 frame={current_frame}")
        logger.info(
            "暂停门闩: 确认停表 frame=%s trigger=%s start=%s method=%s reason=%s%s，"
            "保留 active 等待用户恢复",
            current_frame,
            trigger,
            start,
            method,
            reason,
            latency,
        )

    def _dispatch_next_pause_group(self, current_frame: int) -> bool:
        """
        派发队首 group：发一次键、进入 verifying。

        - gate 非 None 或队列空 → 返回 False。
        - 无窗口 → 保留队首，提示并返回 False。
        - 发键异常 → pop 当前队首（记失败，不重试），返回 False。
        - 成功 → pop、赋 active、进入 verifying，返回 True。
        """
        if self._pause_gate is not None:
            return False
        group = self._pending_pause_groups.peek()
        if group is None:
            return False

        summary = self._group_summary(group)

        win = self._resolve_live_game_window()
        if not win or not win.get("hwnd"):
            self._set_pause_status(f"暂停: 未找到游戏窗 | {summary}")
            logger.warning(
                "派发暂停但未找到游戏窗口，保留队首 trigger=%s: %s",
                group.trigger_frame,
                summary,
            )
            return False

        hwnd = int(win["hwnd"])
        is_emu = looks_like_emulator_window(
            win.get("title", ""), win.get("class_name", "")
        )

        method_used = None
        try:
            if is_emu and getattr(config, "ADB_PREFER_FOR_EMULATOR", True):
                method_used = send_adb_pause_key(getattr(config, "ADB_PAUSE_HOTKEY", "Space"))
            else:
                # PC 非管理员警告（文案为 ESC）
                if (
                    getattr(config, "PAUSE_REQUIRE_ADMIN_FOR_PC", True)
                    and not self._is_admin
                ):
                    msg = "需管理员运行才能对 PC 客户端发暂停 ESC（右键 exe→以管理员身份运行）"
                    self._set_pause_status(f"暂停: {msg}")
                    if not self._admin_warned:
                        self._admin_warned = True
                        logger.warning("%s | 触发: %s", msg, summary)
                        try:
                            from tkinter import messagebox

                            messagebox.showwarning(
                                "自动暂停需要管理员",
                                "已绑定 PC 游戏窗口，但 TimelineTool 未以管理员身份运行。\n\n"
                                "ESC 暂停键很可能无法送达客户端（UAC 完整性隔离）。\n\n"
                                "请：关闭本程序 → 右键 TimelineTool.exe →「以管理员身份运行」\n"
                                "再重新绑定游戏窗后对轴。\n\n"
                                "（若走模拟器 ADB，可不需要管理员。）",
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.debug("管理员提示框失败: %s", e)
                method_used = send_pc_pause_key(
                    hwnd,
                    before_focus=self._drop_topmost_for_pause,
                    after_send=self._restore_topmost_for_pause,
                    hold_ms=getattr(config, "PC_PAUSE_KEY_HOLD_MS", 50),
                )
        except Exception as e:  # noqa: BLE001
            # 输入 API 异常：pop 当前队首（当前组记失败，避免无限重试），不尝试其他通道
            failed = self._pending_pause_groups.pop()
            logger.warning(
                "派发暂停发送异常，丢弃当前组 trigger=%s reason=%s: %s",
                getattr(failed, "trigger_frame", None),
                e,
                summary,
            )
            self._restore_topmost_for_pause()
            self._pause_gate = None
            self._pause_verify = None
            self._active_pause_group = None
            self._set_pause_status(f"暂停失败: 发送异常 ({e})")
            return False

        # 成功：pop、赋 active、进入 verifying
        self._pending_pause_groups.pop()
        self._active_pause_group = group
        self._pause_gate = "verifying"
        self._pause_gate_frame = current_frame
        import time as _time

        self._pause_verify = {
            "method_used": method_used,
            "start_frame": current_frame,
            "start_ts": _time.monotonic(),
            "last_frame": current_frame,
            "stall_count": 0,
            "stall_since": None,
            "trigger_frame": group.trigger_frame,
            "summary": summary,
        }
        admin_tag = "" if self._is_admin else " [非管理员]"
        title_tag = ""
        if win and win.get("title"):
            title_tag = f" →{win['title'][:16]}"
        self._set_pause_status(f"暂停校验 {method_used}{admin_tag}{title_tag}")
        logger.info(
            "自动暂停派发 trigger=%s current=%s pending=%d method=%s admin=%s: %s",
            group.trigger_frame,
            current_frame,
            len(self._pending_pause_groups),
            method_used,
            self._is_admin,
            summary,
        )
        return True

    def _update_pause_gate(self, current_frame: int) -> None:
        """
        发键后的状态机：verifying → frozen → None。

        verifying：用费用尺帧确认「真停」；单帧抖动不算成功。失败调 _mark_pause_failed。
        frozen：current_frame > gate_frame 视为用户恢复 → 清 gate/verify/active，
                同轮后续可立即派发队首。
        """
        import time as _time

        gate = self._pause_gate
        if gate is None:
            return

        if gate == "verifying":
            v = self._pause_verify if isinstance(self._pause_verify, dict) else None
            if not v:
                self._pause_gate = None
                return

            now = _time.monotonic()
            start_frame = int(v.get("start_frame") or current_frame)
            last_frame = int(v.get("last_frame") if v.get("last_frame") is not None else start_frame)
            timeout = float(getattr(config, "PAUSE_VERIFY_TIMEOUT_SEC", 0.45) or 0.45)
            need_stall = int(getattr(config, "PAUSE_VERIFY_STALL_UPDATES", 3) or 3)
            min_stall = float(getattr(config, "PAUSE_GATE_MIN_STALL_SEC", 0.18) or 0.18)
            fail_advance = int(getattr(config, "PAUSE_VERIFY_FAIL_ADVANCE", 6) or 6)

            advanced = current_frame - start_frame
            elapsed = now - float(v.get("start_ts") or now)

            if current_frame > last_frame:
                # 仍在前进
                v["last_frame"] = current_frame
                v["stall_count"] = 0
                v["stall_since"] = None
                self._pause_gate_frame = current_frame
                if advanced >= fail_advance:
                    self._mark_pause_failed(
                        current_frame, f"前进{advanced}帧>={fail_advance}"
                    )
                    return
                if elapsed >= timeout:
                    self._mark_pause_failed(
                        current_frame,
                        f"超时{timeout:.2f}s仍前进 advanced={advanced}",
                    )
                return

            # 帧未增加（相对上一快照）
            stall_count = int(v.get("stall_count") or 0) + 1
            v["stall_count"] = stall_count
            v["last_frame"] = current_frame
            if v.get("stall_since") is None:
                v["stall_since"] = now
            stall_for = now - float(v["stall_since"])
            self._pause_gate_frame = current_frame

            if stall_count >= need_stall and stall_for >= min_stall:
                self._mark_pause_verified(
                    current_frame,
                    f"stall×{stall_count}/{need_stall} ≥{min_stall:.2f}s",
                )
                return

            if elapsed >= timeout:
                # 费用尺可能只在变帧时推送：发键后几乎不前进却迟迟凑不够 stall 样本
                # 绝不能再发键（会取消已成功的暂停）。把「几乎没前进」当成功。
                if advanced <= 1:
                    self._mark_pause_verified(
                        current_frame,
                        f"超时且几乎未前进 advanced={advanced} stall={stall_count}",
                    )
                else:
                    self._mark_pause_failed(
                        current_frame,
                        f"超时未稳定停表 advanced={advanced} stall={stall_count}",
                    )
            return

        if gate == "frozen":
            if current_frame > self._pause_gate_frame:
                pending = len(self._pending_pause_groups)
                logger.info(
                    "用户恢复 frame=%s trigger_gate=%s pending=%d，允许处理下一节点",
                    current_frame,
                    self._pause_gate_frame,
                    pending,
                )
                self._pause_gate = None
                self._pause_verify = None
                self._active_pause_group = None
            else:
                # 未恢复：只更新/保持 gate frame，不派发
                self._pause_gate_frame = current_frame

    def _maybe_auto_pause(self, current_frame: int, *, is_running: bool) -> None:
        # 1) 大幅帧回退 → 清空整个暂停序列（队列/active/gate/verify）
        last = self.pause_engine.last_frame
        if last is not None and current_frame + self.pause_engine.reset_threshold < last:
            self._clear_pause_sequence(f"费用尺帧回退 {last}->{current_frame}")

        # 2) 推进门闩 / 校验（frozen 恢复会在本步把 gate 清成 None）
        self._update_pause_gate(current_frame)

        # 3) 收集本 tick 事件并全部入队（gate 非空也不能阻止入队，防事件丢失）
        events = self.pause_engine.tick(
            current_frame,
            self.tracks,
            is_running=is_running,
            lead_frames=self._get_pause_lead_frames(),
        )
        if events:
            self._queue_pause_events(events)

        # 4) gate 非空时只入队不派发；否则派发队首
        if self._pause_gate is not None:
            return
        self._dispatch_next_pause_group(current_frame)

    def _bind_game_window_click(self) -> None:
        """倒计时后取光标下窗口并保存绑定。"""
        self._set_pause_status("暂停: 3秒内把鼠标移到游戏窗…")
        self.root.update_idletasks()

        def _finish() -> None:
            win = pick_window_under_cursor(timeout_sec=0.05)
            # 再给一次即时采样（主线程已等 3s）
            try:
                import ctypes
                from ctypes import wintypes

                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                from game_window import window_from_point

                win = window_from_point(pt.x, pt.y) or win
            except Exception as e:  # noqa: BLE001
                logger.warning("取光标窗口失败: %s", e)
            if not win or not win.get("title"):
                self._set_pause_status("暂停: 绑定失败")
                return
            bound = BoundWindow(
                title=win.get("title", ""),
                class_name=win.get("class_name", ""),
                hwnd=int(win.get("hwnd") or 0),
            )
            self._bound_window = bound
            try:
                save_bound(self._bound_window_path(), bound)
            except Exception as e:  # noqa: BLE001
                logger.warning("保存绑定失败: %s", e)
            short = bound.title[:24] + ("…" if len(bound.title) > 24 else "")
            # 绑定 PC 客户端时检查管理员
            is_emu = False
            try:
                from adb_input import looks_like_emulator_window

                is_emu = looks_like_emulator_window(
                    bound.title, bound.class_name
                )
            except Exception:  # noqa: BLE001
                pass
            # 对照 MAA：PC 客户端应是标题精确「明日方舟」+ UnityWndClass
            is_maa_pc = bound.title in ("明日方舟", "Arknights") and (
                not bound.class_name or bound.class_name == "UnityWndClass"
            )
            if (
                not is_emu
                and getattr(config, "PAUSE_REQUIRE_ADMIN_FOR_PC", True)
                and not self._is_admin
            ):
                self._set_pause_status(
                    f"已绑 {short} | 非管理员，PC 暂停可能无效"
                )
                logger.warning(
                    "已绑定 PC 窗但未管理员: %s — 自动暂停可能被 UIPI 拦截",
                    bound,
                )
                try:
                    from tkinter import messagebox

                    messagebox.showwarning(
                        "建议以管理员运行",
                        f"已绑定：{bound.title}\n\n"
                        "这是 PC 游戏窗口。未以管理员身份运行时，\n"
                        "自动暂停（Space）常常无法送达客户端。\n\n"
                        "请右键 TimelineTool.exe →「以管理员身份运行」后重试。\n"
                        "模拟器 + ADB 路径一般不需要管理员。",
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                tag = " [MAA-PC]" if is_maa_pc else (" [模拟器]" if is_emu else "")
                self._set_pause_status(f"暂停: 已绑 {short}{tag}")
            logger.info(
                "已绑定游戏窗: hwnd=%s title=%r class=%r pid=%s size=%sx%s "
                "admin=%s emu=%s maa_pc=%s",
                bound.hwnd,
                bound.title,
                bound.class_name,
                win.get("pid"),
                win.get("width"),
                win.get("height"),
                self._is_admin,
                is_emu,
                is_maa_pc,
            )

        # 3 秒后采样（期间用户把鼠标移到目标窗）
        self.root.after(3000, _finish)

    def _update_display(self):
        self._distribute_heights()
        for track in self.tracks:
            track.update_display()

        # 更新 active track 的添加/删除按钮图标
        active = self.active_track
        if active and active.mode.get() == "打轴模式" and hasattr(self, 'add_remove_btn'):
            icon_name = "remove" if getattr(active, 'node_on_cursor', None) else "add"
            text = "移除节点" if getattr(active, 'node_on_cursor', None) else "添加节点"
            icon = self.icons.get(icon_name)
            if icon:
                self.add_remove_btn.config(image=icon)
            if hasattr(self.add_remove_btn, '_tooltip'):
                self.add_remove_btn._tooltip.set_text(text)

    def _setup_keybindings(self):
        """绑定键盘事件：缩放与移动。"""
        self.root.bind("<Up>", self._on_key_up)
        self.root.bind("<Down>", self._on_key_down)
        self.root.bind("<Left>", self._on_key_left)
        self.root.bind("<Right>", self._on_key_right)

    def _on_key_up(self, event):
        """上箭头：单轨道缩放增大；Ctrl+上箭头：全局缩放增大。"""
        if self.is_time_flowing:
            return
        if event.state & 0x0004:  # Ctrl 按下
            self._apply_global_zoom(0.1)
        else:
            self._apply_track_zoom(0.1)

    def _on_key_down(self, event):
        """下箭头：单轨道缩放减小；Ctrl+下箭头：全局缩放减小。"""
        if self.is_time_flowing:
            return
        if event.state & 0x0004:  # Ctrl 按下
            self._apply_global_zoom(-0.1)
        else:
            self._apply_track_zoom(-0.1)

    def _move_timeline_by_frames(self, frame_delta, *, track=None) -> None:
        """手动移动时间轴；键盘与轨道滚轮共用同一帧步进。"""
        if self.is_time_flowing or not frame_delta:
            return
        target = track or self.active_track
        if target and target.magnet_mode.get():
            target.magnet_mode.set(False)
            logger.info("手动移动时间轴，解除磁铁吸附。")
        self.timeline_offset += frame_delta
        self._update_display()

    def _on_key_left(self, event):
        """左箭头：向左移动一个逻辑帧。"""
        self._move_timeline_by_frames(-config.KEYBOARD_SCROLL_STEP)

    def _on_key_right(self, event):
        """右箭头：向右移动一个逻辑帧。"""
        self._move_timeline_by_frames(config.KEYBOARD_SCROLL_STEP)

    def _apply_global_zoom(self, delta):
        """统一调整所有轨道的缩放比例，使所有轨道倍率完全一致。"""
        new_zoom = round(self.global_zoom + delta, 1)
        new_zoom = max(config.MIN_ZOOM, min(config.MAX_ZOOM, new_zoom))
        if new_zoom != self.global_zoom:
            self.global_zoom = new_zoom
            # 只更新全局像素比例，不重置窗口尺寸
            self.scaled_pixels_per_frame = config.PIXELS_PER_FRAME * self.scaling_factor * self.global_zoom
            # 统一所有轨道的缩放倍率
            for track in self.tracks:
                track.track_zoom = 1.0
            logger.info(f"全局缩放调整为 {self.global_zoom}x，所有轨道已统一为 1.0x")
            self._update_display()

    def _apply_track_zoom(self, delta):
        """调整当前激活轨道的缩放比例。"""
        active = self.active_track
        if not active:
            return
        new_zoom = round(active.track_zoom + delta, 1)
        new_zoom = max(config.MIN_ZOOM, min(config.MAX_ZOOM, new_zoom))
        if new_zoom != active.track_zoom:
            active.track_zoom = new_zoom
            logger.info(f"[{active.name}] 轨道缩放调整为 {active.track_zoom}x")
            self._update_display()

    def _update_ui_for_mode(self, *args):
        """根据当前激活轨道的模式更新UI。"""
        # 清理旧的 switch_frame（如果有）
        for child in self.ops_frame.winfo_children():
            if getattr(child, '_is_mode_switch', False):
                child.destroy()

        for widget in self.dynamic_ops_frame.winfo_children():
            widget.destroy()
        for i in range(4):
            self.dynamic_ops_frame.rowconfigure(i, weight=1)

        active = self.active_track
        if not active:
            return

        if active.mode.get() == "打轴模式":
            # 打轴：保留磁铁状态（开=蓝线跟费用尺，关=可自由拖；可用「回正」）
            self._create_editing_buttons()
        else:
            # 对轴模式强制开启吸附
            active.magnet_mode.set(True)
            self._create_following_buttons()

        # 重建模式切换栏
        switch_frame = ttk.Frame(self.ops_frame, style="TFrame")
        switch_frame._is_mode_switch = True
        switch_frame.pack(side=BOTTOM, fill=X, pady=self.scaled_pad_m)

        # 重新调整 all_mode_frame 位置，确保它在 switch_frame 上方
        self._refresh_all_mode_visibility()
        switch_frame.columnconfigure((0, 1), weight=1)
        ttk.Radiobutton(switch_frame, text="打轴", variable=active.mode, value="打轴模式",
                        style="Outline.Toolbutton").grid(row=0, column=0, sticky="ew", padx=self.scaled_pad_xs)
        ttk.Radiobutton(switch_frame, text="对轴", variable=active.mode, value="对轴模式",
                        style="Outline.Toolbutton").grid(row=0, column=1, sticky="ew", padx=self.scaled_pad_xs)

    @property
    def active_track(self):
        if 0 <= self.active_track_index < len(self.tracks):
            return self.tracks[self.active_track_index]
        return None

    @property
    def is_time_flowing(self):
        """费用尺时间是否正在流逝（用于禁止跳转、缩放等操作）。"""
        return self._is_time_flowing

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def _create_grid_button(self, parent, r, c, text, icon_name, command):
        icon = self.icons.get(icon_name)
        btn = ttk.Button(parent, command=command, style="Tool.TButton")
        if icon:
            btn.config(image=icon)
        else:
            btn.config(text=text)
        btn._tooltip = SimpleTooltip(btn, text=text)
        btn.grid(row=r, column=c, padx=self.scaled_pad_s, pady=self.scaled_pad_s, sticky="nsew")
        return btn

    def _create_grid_toggle_button(self, parent, r, c, text_on, text_off, var, on_icon, off_icon, command=None):
        btn = ttk.Button(parent, style="Tool.TButton")
        tooltip = SimpleTooltip(btn, text=text_on)

        def update_display():
            is_on = var.get()
            icon_name = on_icon if is_on else off_icon
            current_text = text_on if is_on else text_off
            icon = self.icons.get(icon_name)
            tooltip.set_text(current_text)
            if icon:
                btn.config(image=icon, text="")
            else:
                btn.config(text=current_text, image="")

        def toggler():
            var.set(not var.get())
            update_display()
            if command:
                command()

        btn.config(command=toggler)
        update_display()
        btn.grid(row=r, column=c, padx=self.scaled_pad_s, pady=self.scaled_pad_s, sticky="nsew")
        return btn

    def _create_editing_buttons(self):
        """为“打轴模式”创建操作按钮（打开/保存已移至顶栏）。"""
        frame = self.dynamic_ops_frame
        active = self.active_track
        self.add_remove_btn = self._create_grid_button(
            frame, 0, 0, "添加/移除", "add", active.add_or_remove_node_at_cursor
        )
        self._create_grid_button(frame, 0, 1, "切换颜色", "color", active.change_node_color_at_cursor)
        self._create_grid_button(frame, 0, 2, "节点配置", "rename", active.configure_node_at_cursor)

        def on_magnet_toggle():
            if not active.magnet_mode.get():
                self.timeline_offset = self.current_game_frame
                logger.debug(f"手动关闭磁铁模式，时间轴位置同步到: {self.timeline_offset}")
            self._mark_dirty()

        self._create_grid_toggle_button(
            frame, 1, 0, "磁铁: 开", "磁铁: 关", active.magnet_mode,
            "magnet_on", "magnet_off", command=on_magnet_toggle,
        )
        self._create_track_pause_toggle(frame, 1, 1, active)

    def _create_lead_controls(self, parent, active) -> None:
        """提醒提前与暂停提前各占一行，避免窄操作面板横向截断。"""
        alert_row = ttk.Frame(parent, style="TFrame")
        alert_row.grid(row=0, column=0, sticky="w")
        ttk.Label(
            alert_row,
            text="提醒提前(帧):",
            font=(config.FONT_FAMILY, self.scaled_font_normal),
        ).pack(side=LEFT, padx=self.scaled_pad_m)
        alert_spin = ttk.Spinbox(
            alert_row,
            from_=0,
            to_=300,
            textvariable=active.alert_lead_var,
            width=5,
        )
        alert_spin.pack(side=LEFT, padx=self.scaled_pad_m)
        alert_spin.bind("<Return>", lambda e: None)

        pause_row = ttk.Frame(parent, style="TFrame")
        pause_row.grid(row=1, column=0, sticky="w", pady=(self.scaled_pad_s, 0))
        ttk.Label(
            pause_row,
            text="暂停提前(帧):",
            font=(config.FONT_FAMILY, self.scaled_font_normal),
        ).pack(side=LEFT, padx=self.scaled_pad_m)
        pause_spin = ttk.Spinbox(
            pause_row,
            from_=0,
            to_=30,
            textvariable=self.pause_lead_var,
            width=4,
        )
        pause_spin.pack(side=LEFT, padx=self.scaled_pad_m)
        pause_spin.bind("<Return>", lambda e: self._on_pause_lead_changed())
        pause_spin.bind("<FocusOut>", lambda e: self._on_pause_lead_changed())

    def _create_following_buttons(self):
        """为“对轴模式”创建操作按钮。"""
        frame = self.dynamic_ops_frame
        active = self.active_track
        self._create_grid_toggle_button(
            frame, 0, 0, "声音提醒: 开", "声音提醒: 关", active.sound_alert_enabled,
            "sound_on", "sound_off",
        )
        self._create_grid_toggle_button(
            frame, 0, 1, "视觉提醒: 开", "视觉提醒: 关", active.visual_alert_enabled,
            "visual_on", "visual_off",
        )
        self._create_track_pause_toggle(frame, 0, 2, active)

        self._create_grid_button(frame, 1, 0, "节点配置", "rename", active.configure_node_at_cursor)

        lead_frame = ttk.Frame(frame, style="TFrame")
        lead_frame.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(self.scaled_pad_xl, 0),
        )
        self._create_lead_controls(lead_frame, active)

    def _create_track_pause_toggle(self, parent, r, c, active):
        """轨道自动暂停总闸（对轴生效）。专用暂停图标，不用喇叭。"""
        def on_toggle():
            self._mark_dirty()
            state = "开" if active.pause_enabled.get() else "关"
            self._set_pause_status(f"轨暂停: {state} [{active.name}]")
            try:
                active.update_display()
            except Exception:  # noqa: BLE001
                self._update_display()

        self._create_grid_toggle_button(
            parent, r, c,
            "轨暂停: 开", "轨暂停: 关",
            active.pause_enabled,
            "pause_on", "pause_off",
            command=on_toggle,
        )

    # ------------------------------------------------------------------
    # Drag / Resize events
    # ------------------------------------------------------------------
    def _mark_dirty(self):
        """标记当前时间轴有未保存的修改。"""
        self._dirty = True

    def _mark_clean(self):
        """标记当前时间轴已保存。"""
        self._dirty = False

    def _on_close_request(self):
        """处理窗口关闭请求，检查未保存修改。"""
        if self._dirty:
            from tkinter import messagebox
            if not messagebox.askyesno("未保存的修改", "当前时间轴有未保存的修改，确认要退出吗？", parent=self.root):
                return
        self.root.quit()

    def _on_resize_height_start(self, event):
        self._resize_height_data = {"start_y": event.y_root, "start_height": self.scaled_win_height}

    def _on_resize_height_motion(self, event):
        dy = event.y_root - self._resize_height_data["start_y"]
        new_height = max(self._get_minimum_height(),
                         self._resize_height_data["start_height"] + dy)
        self.scaled_win_height = new_height
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{self.scaled_win_width}x{new_height}+{x}+{y}")
        self._update_display()

    def _on_resize_width_start(self, event):
        self._resize_width_data = {"start_x": event.x_root, "start_width": self.scaled_win_width}

    def _on_resize_width_motion(self, event):
        dx = event.x_root - self._resize_width_data["start_x"]
        new_width = max(self._get_minimum_width(),
                        self._resize_width_data["start_width"] + dx)
        self.scaled_win_width = new_width
        if not self.ops_collapsed:
            self.ops_frame.config(width=new_width // 3)
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{new_width}x{self.scaled_win_height}+{x}+{y}")
        self._update_display()

    def on_timeline_drag_start(self, event):
        self.is_animating = False
        self.is_inertial_scrolling = False
        self._timeline_drag_data.update({"x": event.x, "start_x": event.x, "is_dragging": False, "last_dx": 0})

    def on_timeline_drag_motion(self, event, track):
        if not self._timeline_drag_data["is_dragging"] and abs(
                event.x - self._timeline_drag_data["start_x"]) > self.scaled_drag_threshold:
            self._timeline_drag_data["is_dragging"] = True

        if not self._timeline_drag_data["is_dragging"]:
            return

        dx = event.x - self._timeline_drag_data["x"]
        self._timeline_drag_data["last_dx"] = dx
        effective_ppf = self.scaled_pixels_per_frame * track.track_zoom
        frame_delta = dx / effective_ppf if effective_ppf else 0

        if track.magnet_mode.get():
            # 磁铁锁定时禁止通过拖拽解除吸附
            if abs(dx) > config.MAGNET_BREAK_THRESHOLD and not getattr(track, 'magnet_locked', False):
                logger.info("通过大幅度拖拽已脱离磁铁模式。")
                track.magnet_mode.set(False)
                self.timeline_offset = self.current_game_frame - frame_delta
        else:
            self.timeline_offset -= frame_delta
        self._timeline_drag_data["x"] = event.x

    def on_timeline_drag_release(self, event, track):
        was_dragging = self._timeline_drag_data["is_dragging"]
        self._timeline_drag_data["is_dragging"] = False

        if was_dragging:
            if not track.magnet_mode.get():
                effective_ppf = self.scaled_pixels_per_frame * track.track_zoom
                self.inertia_velocity = self._timeline_drag_data["last_dx"] / effective_ppf if effective_ppf else 0
                self.is_inertial_scrolling = True
        else:
            if not track.magnet_mode.get():
                width = track.canvas.winfo_width()
                effective_ppf = self.scaled_pixels_per_frame * track.track_zoom
                if effective_ppf <= 0:
                    return
                clicked_frame = int(self.timeline_offset + (event.x - width / 2) / effective_ppf)
                node_to_snap = track._find_node_at(clicked_frame, tolerance=config.NODE_CLICK_TOLERANCE)
                if node_to_snap:
                    logger.info(f"单击吸附到节点: {node_to_snap['name']} ({node_to_snap['frame']})")
                    self._animate_scroll_to(node_to_snap['frame'])

    def _animate_scroll_to(self, target_frame):
        """平滑滚动到指定的目标帧。"""
        if self.is_animating:
            return
        self.is_inertial_scrolling = False
        self.is_animating = True
        self.animation_target_frame = int(target_frame)

    def _on_window_drag_start(self, event):
        """处理窗口拖动的开始事件。使用屏幕坐标避免抖动。"""
        self._window_dragging = True
        self._window_drag_data = {"x": event.x_root, "y": event.y_root}

    def _on_window_drag_motion(self, event):
        """处理窗口的拖动事件。使用屏幕坐标避免抖动。"""
        if not self._window_dragging or not self._window_drag_data:
            return
        dx = event.x_root - self._window_drag_data["x"]
        dy = event.y_root - self._window_drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._window_drag_data["x"] = event.x_root
        self._window_drag_data["y"] = event.y_root

    # 这些控件自身要处理点击，不启动窗口拖动
    _NO_WINDOW_DRAG_CLASSES = {
        "Button", "TButton", "Entry", "TEntry", "Spinbox", "TSpinbox",
        "Canvas", "TRadiobutton", "Radiobutton", "TCheckbutton", "Checkbutton",
        "TCombobox", "Listbox", "Text", "Scrollbar", "TScrollbar",
        "Scale", "TScale",
    }

    def _widget_blocks_window_drag(self, widget) -> bool:
        """
        是否禁止拖窗：
        - 缩放条 / 显式 _no_hud_drag
        - 按钮、时间轴画布、输入框等
        顶栏 _hud_drag_zone 内的空白允许拖（按钮仍拦截）。
        """
        cur = widget
        in_drag_zone = False
        while cur is not None:
            try:
                if getattr(cur, "_no_hud_drag", False):
                    return True
                if getattr(cur, "_hud_drag_zone", False):
                    in_drag_zone = True
            except Exception:  # noqa: BLE001
                pass
            # 底部/右侧缩放条整棵子树禁止拖窗
            if cur is getattr(self, "bottom_resize_handle", None):
                return True
            if cur is getattr(self, "right_resize_handle", None):
                return True
            try:
                cls = cur.winfo_class()
            except tk.TclError:
                break
            if cls in self._NO_WINDOW_DRAG_CLASSES:
                return True
            try:
                cur = cur.master
            except tk.TclError:
                break
        # 只有显式标记的顶栏/迷你栏空白区可拖动；其它普通标签和 Frame
        # 可能承载点击交互，均应放行给自身。
        return not in_drag_zone

    def _on_global_window_press(self, event):
        """全局左键：空白处开始拖窗，交互控件与缩放条放行。"""
        try:
            if event.widget.winfo_toplevel() is not self.root:
                self._window_dragging = False
                return
        except tk.TclError:
            self._window_dragging = False
            return
        if self._widget_blocks_window_drag(event.widget):
            self._window_dragging = False
            self._window_drag_data = None
            return
        self._on_window_drag_start(event)

    def _on_global_window_motion(self, event):
        if self._window_dragging:
            self._on_window_drag_motion(event)

    def _on_global_window_release(self, event):
        self._window_dragging = False

    def _minimize_window(self):
        """最小化：只保留细条（恢复 / 关闭）。"""
        if self._minimized:
            return
        self._minimized = True
        try:
            self._restore_geometry = self.root.geometry()
        except tk.TclError:
            self._restore_geometry = None
        # 收起主界面
        try:
            self._main_frame.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        bar_h = max(28, int(28 * self.scaling_factor))
        bar_w = max(160, int(180 * self.scaling_factor))
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self._mini_bar.pack(fill=X, padx=self.scaled_pad_s, pady=self.scaled_pad_s)
        self.root.geometry(f"{bar_w}x{bar_h}+{x}+{y}")
        logger.info("窗口已最小化")

    def _restore_window(self):
        """从最小化细条恢复完整 HUD。"""
        if not self._minimized:
            return
        self._minimized = False
        try:
            self._mini_bar.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._main_frame.pack(expand=True, fill=BOTH)
        except Exception:  # noqa: BLE001
            pass
        if self._restore_geometry:
            self.root.geometry(self._restore_geometry)
        else:
            self.root.geometry(f"{self.scaled_win_width}x{self.scaled_win_height}")
        self._update_display()
        logger.info("窗口已恢复")

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------
    def _load_timeline(self):
        """通过文件对话框加载时间轴文件。"""
        data, filepath = load_timeline_from_file(self.root)
        if data is None:
            return
        self._load_file_data(data, filepath)

    def _load_file(self, filepath):
        """从指定路径加载时间轴文件（不弹对话框，用于重启后重新打开原文件）。"""
        from file_io import _load_from_path
        try:
            data = _load_from_path(filepath)
            self._load_file_data(data, filepath)
        except Exception as e:
            logger.error(f"加载文件失败: {filepath}，错误: {e}", exc_info=True)
            self.add_track()

    def _load_file_data(self, data, filepath):
        """加载时间轴数据并更新UI状态。"""
        tracks_data = data.get("tracks", [])
        # 清除现有轨道
        if self._mode_trace_id:
            try:
                self.tracks[self.active_track_index].mode.trace_remove("write", self._mode_trace_id)
            except (tk.TclError, IndexError):
                pass
            self._mode_trace_id = None
        for track in self.tracks:
            track.frame.destroy()
        self.tracks.clear()
        self.active_track_index = 0
        for td in tracks_data:
            self.add_track(td)
        self._adjust_window_height()
        self._current_file = filepath
        self._mark_clean()

    def _save_timeline(self):
        if not self.tracks:
            return
        tracks_data = [t.dump_data() for t in self.tracks]

        def _on_save_done(ok, filepath):
            if ok:
                self._current_file = filepath
                self._mark_clean()

        if self.naming_mgr.is_enabled() and self.naming_mgr.get_presets():
            def on_dialog_result(values):
                if values is None:
                    return
                filename = self.naming_mgr.build_filename(values, len(self.tracks))
                ok, filepath = save_timeline_to_file(tracks_data, self.root, initialfile=filename)
                _on_save_done(ok, filepath)
            presets = self.naming_mgr.get_all_presets()
            default_preset = self.naming_mgr.get_default_preset()
            NamingDialog(self.root, presets, default_preset, len(self.tracks), on_dialog_result)
            return

        ok, filepath = save_timeline_to_file(tracks_data, self.root)
        _on_save_done(ok, filepath)

    def _do_autoload(self, path):
        """从临时文件自动加载时间轴数据（兼容旧版，不再主动使用）。"""
        import json as _json
        logger.info(f"[_do_autoload] 尝试加载临时文件: {path}")
        try:
            if not os.path.exists(path):
                logger.warning(f"[_do_autoload] 临时文件不存在: {path}")
                self.add_track()
                return
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            tracks_data = data.get("tracks", [])
            logger.info(f"[_do_autoload] 读取到 {len(tracks_data)} 个轨道")
            for i, td in enumerate(tracks_data):
                nodes = td.get("nodes", [])
                node_info = f"  轨道{i} '{td.get('name')}' 节点数={len(nodes)}"
                if nodes:
                    node_info += f" 首节点={nodes[0].get('name')}@{nodes[0].get('frame')} 末节点={nodes[-1].get('name')}@{nodes[-1].get('frame')}"
                logger.info(node_info)
            if not tracks_data:
                self.add_track()
                return
            for td in tracks_data:
                self.add_track(td)
            try:
                os.remove(path)
                logger.info(f"[_do_autoload] 已删除临时文件: {path}")
            except OSError as e:
                logger.warning(f"[_do_autoload] 删除临时文件失败: {e}")
            logger.info(f"自动加载成功: {path}")
        except Exception as e:
            logger.error(f"自动加载失败: {e}", exc_info=True)
            self.add_track()

    def _restart_app(self):
        """重启打轴器进程。不保留内存中的编辑，而是重新打开原文件（如果有）。"""
        from tkinter import messagebox
        import os, sys, time

        # 根据是否有打开文件和是否有未保存修改，组合不同的提示文案
        if self._dirty and self._current_file:
            msg = (f"当前时间轴有未保存的修改，重启将放弃未保存的内容，"
                   f"并重新打开原文件。\n\n文件: {self._current_file}\n\n确认要重启吗？")
            title = "未保存的修改"
        elif self._dirty and not self._current_file:
            msg = ("当前时间轴有未保存的修改，重启将创建新的空白时间轴。"
                   "\n\n确认要重启吗？")
            title = "未保存的修改"
        elif not self._dirty and self._current_file:
            msg = f"是否重启打轴器并重新打开当前文件？\n\n{self._current_file}"
            title = "确认重启"
        else:
            msg = "是否重启打轴器？"
            title = "确认重启"

        if not messagebox.askyesno(title, msg, parent=self.root):
            return

        # 如果有打开的文件，通过环境变量传递文件路径给子进程
        if self._current_file:
            os.environ['TIMELINE_OPEN_FILE'] = self._current_file
            logger.info(f"[_restart_app] 设置环境变量 TIMELINE_OPEN_FILE={self._current_file}")
        else:
            # 清除可能存在的环境变量，确保子进程创建默认轨道
            os.environ.pop('TIMELINE_OPEN_FILE', None)
            os.environ.pop('TIMELINE_AUTOLOAD', None)

        proc = None
        try:
            child_env = os.environ.copy()
            child_env.pop('_MEIPASS2', None)

            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP

            exe_path = sys.executable
            if getattr(sys, 'frozen', False):
                proc = subprocess.Popen([exe_path], env=child_env, creationflags=flags)
            else:
                main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')
                proc = subprocess.Popen([exe_path, main_py], env=child_env, creationflags=flags)
            logger.info(f"已启动新进程 PID={proc.pid}，等待子进程完成解压...")
        except Exception as e:
            logger.error(f"启动新进程失败: {e}", exc_info=True)
            messagebox.showerror("重启失败", f"启动新进程失败:\n{e}", parent=self.root)
            return

        # 隐藏原窗口，给子进程留出足够时间完成 onefile 解压和启动
        self.root.withdraw()
        # 分步等待，定期检查子进程是否存活
        wait_total = 10
        check_interval = 1
        for i in range(wait_total // check_interval):
            time.sleep(check_interval)
            if proc is not None:
                ret = proc.poll()
                if ret is not None:
                    if ret == 0:
                        logger.info(f"子进程已正常退出（返回码=0），父进程跟随退出")
                        break
                    else:
                        logger.error(f"子进程异常退出，返回码={ret}")
                        self.root.deiconify()
                        messagebox.showerror("重启失败", f"子进程启动后异常退出（返回码={ret}）。\n"
                                            f"可能原因：PyInstaller onefile 临时目录冲突、"
                                            f"杀毒软件拦截或系统 Job Object 限制。", parent=self.root)
                        return
        # 使用 destroy() 彻底释放 tkinter 资源，确保原进程干净退出
        self.root.destroy()

