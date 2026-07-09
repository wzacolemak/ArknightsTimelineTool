import tkinter as tk
from tkinter import ttk, simpledialog, TclError
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
from pause_engine import PauseEngine
from game_window import (
    BoundWindow,
    load_bound,
    save_bound,
    resolve_game_window,
    pick_window_under_cursor,
)
from hotkey_send import send_pause_key

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

        # --- UI设置与启动 ---
        self._setup_styles()
        self._setup_ui()
        self._setup_keybindings()

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
        icon_files = {"open": "open.png", "save": "save.png", "magnet_on": "magnet_on.png",
                      "magnet_off": "magnet_off.png", "add": "add.png", "remove": "remove.png", "color": "color.png",
                      "sound_on": "sound_on.png", "sound_off": "sound_off.png", "visual_on": "visual_on.png",
                      "visual_off": "visual_off.png", "rename": "rename.png", "restart": "start.png"}
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

        # 拖动窗体的专用手柄按钮
        drag_handle = ttk.Button(self.track_selector_frame, text="⋮⋮", cursor="fleur",
                                 style="Tool.TButton", width=2)
        drag_handle.pack(side=LEFT, padx=(0, self.scaled_pad_s))
        drag_handle.bind("<ButtonPress-1>", self._on_window_drag_start)
        drag_handle.bind("<B1-Motion>", self._on_window_drag_motion)

        self.add_track_btn = ttk.Button(self.track_selector_frame, text="新建轨道", command=self._add_new_track,
                                        style="Tool.TButton")
        self.add_track_btn.pack(side=LEFT, padx=self.scaled_pad_s)
        self.remove_track_btn = ttk.Button(self.track_selector_frame, text="删除轨道",
                                           command=self._remove_active_track, style="Tool.TButton")
        self.remove_track_btn.pack(side=LEFT, padx=self.scaled_pad_s)

        self.track_buttons_frame = ttk.Frame(self.track_selector_frame, style="TFrame")
        self.track_buttons_frame.pack(side=LEFT, fill=X, expand=True, padx=self.scaled_pad_m)

        # 红色叉号关闭按钮（最右侧，先 pack 保证在最右边）
        close_btn = ttk.Button(self.track_selector_frame, text="✕", command=self._on_close_request,
                               style="Danger.TButton", width=2)
        close_btn.pack(side=RIGHT, padx=(self.scaled_pad_s, 0))

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

        # 折叠/展开左侧操作面板按钮（pack 在 restart 之后，确保显示在 restart 左侧）
        self.collapse_btn = ttk.Button(self.track_selector_frame, text="◀", command=self._toggle_ops_panel,
                                       style="Tool.TButton", width=2)
        self.collapse_btn.pack(side=RIGHT, padx=self.scaled_pad_s)
        self.collapse_btn._tooltip = SimpleTooltip(self.collapse_btn, text="隐藏操作面板")

        # --- 底部 resize handle（双横线，调高度） ---
        # 注意：必须在 content_frame 之前 pack，否则 expand=True 的 content_frame
        # 会抢占全部剩余空间，导致 bottom_resize_handle 被挤出可视区域。
        self.bottom_resize_handle = tk.Frame(main_frame, bg="#3e4451", cursor="sb_v_double_arrow",
                                             height=self.scaled_bottom_handle_height)
        self.bottom_resize_handle.pack_propagate(False)
        bottom_label = tk.Label(self.bottom_resize_handle, text="━━", bg="#3e4451", fg="#5c6370",
                                font=(config.FONT_FAMILY, self.scaled_font_normal))
        bottom_label.pack(expand=True)
        for w in (self.bottom_resize_handle, bottom_label):
            w.bind("<ButtonPress-1>", self._on_resize_height_start)
            w.bind("<B1-Motion>", self._on_resize_height_motion)

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
        right_label = tk.Label(self.right_resize_handle, text="┃┃", bg="#3e4451", fg="#5c6370",
                               font=(config.FONT_FAMILY, self.scaled_font_normal))
        right_label.pack(expand=True)
        self.right_resize_handle.pack(side=RIGHT, fill=Y, padx=(0, self.scaled_pad_m), pady=self.scaled_pad_m)
        for w in (self.right_resize_handle, right_label):
            w.bind("<ButtonPress-1>", self._on_resize_width_start)
            w.bind("<B1-Motion>", self._on_resize_width_motion)

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
        # 全新轨道默认关闭磁铁，让用户可以自由移动时间轴
        if track_data is None:
            track.magnet_mode.set(False)
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
            widget.destroy()
        self.track_buttons = []
        for idx, track in enumerate(self.tracks):
            btn = ttk.Button(self.track_buttons_frame, text=track.name,
                             command=lambda t=track: self.set_active_track(t),
                             style="Tool.TButton")
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

                    # 自动暂停：帧前进时做边沿检测
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
                        for track in self.tracks:
                            if getattr(track, 'magnet_locked', False):
                                track.magnet_locked = False
                                if not getattr(track, '_magnet_unlock_log_done', False):
                                    logger.info(f"[{track.name}] 时间暂停，解除磁铁吸附锁定。")
                                    track._magnet_unlock_log_done = True

                    self._last_game_frame = current_frame
                else:
                    # 尺子未运行：解除锁定并重置帧数跟踪
                    self._is_time_flowing = False
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
    def _bound_window_path(self) -> str:
        """绑定窗口缓存路径：开发模式项目根，打包则 exe 同级。"""
        import sys

        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base = (
                os.path.dirname(script_dir)
                if os.path.basename(script_dir) == "timeline_tool"
                else script_dir
            )
        return os.path.join(base, config.BOUND_WINDOW_FILE)

    def _set_pause_status(self, text: str) -> None:
        self._pause_status = text
        label = getattr(self, "pause_status_label", None)
        if label is not None:
            try:
                label.config(text=text)
            except TclError:
                pass

    def _maybe_auto_pause(self, current_frame: int, *, is_running: bool) -> None:
        events = self.pause_engine.tick(
            current_frame, self.tracks, is_running=is_running
        )
        if not events:
            return
        win = resolve_game_window(
            getattr(config, "GAME_WINDOW_TITLE_KEYWORDS", []),
            self._bound_window,
        )
        hwnd = win["hwnd"] if win else None
        if not hwnd:
            self._set_pause_status("暂停: 未找到游戏窗")
            logger.warning(
                "触发暂停但未找到游戏窗口（可点「绑定游戏窗」）: %s", events
            )
            return
        hotkey = getattr(config, "PAUSE_HOTKEY", "Space")
        focus = getattr(config, "FOCUS_GAME_BEFORE_SEND", True)
        for ev in events:
            try:
                send_pause_key(hotkey=hotkey, hwnd=hwnd, focus_before_send=focus)
                self._set_pause_status(
                    f"暂停: [{ev['track_name']}] {ev['name']}@{ev['frame']}"
                )
                logger.info(
                    "自动暂停: track=%s frame=%s name=%s",
                    ev["track_name"],
                    ev["frame"],
                    ev["name"],
                )
            except Exception as e:  # noqa: BLE001
                self._set_pause_status(f"暂停失败: {e}")
                logger.warning("发送暂停键失败: %s", e)

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
            self._set_pause_status(f"暂停: 已绑 {short}")
            logger.info("已绑定游戏窗: %s", bound)

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

    def _on_key_left(self, event):
        """左箭头：向左移动时间轴；若处于吸附状态则自动解除。"""
        if self.is_time_flowing:
            return
        active = self.active_track
        if active and active.magnet_mode.get():
            active.magnet_mode.set(False)
            logger.info("通过左箭头键解除磁铁吸附。")
        self.timeline_offset -= config.KEYBOARD_SCROLL_STEP
        self._update_display()

    def _on_key_right(self, event):
        """右箭头：向右移动时间轴；若处于吸附状态则自动解除。"""
        if self.is_time_flowing:
            return
        active = self.active_track
        if active and active.magnet_mode.get():
            active.magnet_mode.set(False)
            logger.info("通过右箭头键解除磁铁吸附。")
        self.timeline_offset += config.KEYBOARD_SCROLL_STEP
        self._update_display()

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
            # 打轴模式自动关闭磁铁，让用户自由移动时间轴
            active.magnet_mode.set(False)
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
        """为“打轴模式”创建操作按钮。"""
        frame = self.dynamic_ops_frame
        active = self.active_track
        self._create_grid_button(frame, 0, 0, "打开", "open", self._load_timeline)
        self._create_grid_button(frame, 0, 1, "保存", "save", self._save_timeline)
        self.add_remove_btn = self._create_grid_button(frame, 0, 2, "添加/移除", "add",
                                                       active.add_or_remove_node_at_cursor)
        self._create_grid_button(frame, 1, 0, "切换颜色", "color", active.change_node_color_at_cursor)
        self._create_grid_button(frame, 1, 1, "重命名", "rename", active.rename_node_at_cursor)

        def on_magnet_toggle():
            if not active.magnet_mode.get():
                self.timeline_offset = self.current_game_frame
                logger.debug(f"手动关闭磁铁模式，时间轴位置同步到: {self.timeline_offset}")

        self._create_grid_toggle_button(frame, 1, 2, "磁铁: 开", "磁铁: 关", active.magnet_mode, "magnet_on",
                                        "magnet_off", command=on_magnet_toggle)

    def _create_following_buttons(self):
        """为“对轴模式”创建操作按钮。"""
        frame = self.dynamic_ops_frame
        active = self.active_track
        self._create_grid_button(frame, 0, 0, "打开", "open", self._load_timeline)
        self._create_grid_toggle_button(frame, 0, 1, "声音提醒: 开", "声音提醒: 关", active.sound_alert_enabled,
                                        "sound_on", "sound_off")
        self._create_grid_toggle_button(frame, 0, 2, "视觉提醒: 开", "视觉提醒: 关", active.visual_alert_enabled,
                                        "visual_on", "visual_off")
        lead_frame = ttk.Frame(frame, style="TFrame")
        lead_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(self.scaled_pad_xl, 0))
        ttk.Label(lead_frame, text="提醒提前(帧):", font=(config.FONT_FAMILY, self.scaled_font_normal)).pack(
            side=LEFT, padx=self.scaled_pad_m)
        spinbox = ttk.Spinbox(
            lead_frame,
            from_=0,
            to_=300,
            textvariable=active.alert_lead_var,
            width=5
        )
        spinbox.pack(side=LEFT, padx=self.scaled_pad_m)
        spinbox.bind('<Return>', lambda e: None)  # TimelineTrack 内部已处理 trace

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
        self._window_drag_data = {"x": event.x_root, "y": event.y_root}

    def _on_window_drag_motion(self, event):
        """处理窗口的拖动事件。使用屏幕坐标避免抖动。"""
        dx = event.x_root - self._window_drag_data["x"]
        dy = event.y_root - self._window_drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._window_drag_data["x"] = event.x_root
        self._window_drag_data["y"] = event.y_root

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

