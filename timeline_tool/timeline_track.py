import copy
import tkinter as tk
from tkinter import ttk, simpledialog, font
import logging
import math

from PIL import Image, ImageDraw, ImageTk

import config
from utils import format_frame_time
from operator_portrait_manager import OperatorPortraitManager

logger = logging.getLogger(__name__)


def render_antialiased_diamond(
    *,
    fill: str,
    outline: str,
    outline_width: int,
    half_width: float,
    half_height: float,
    oversample: int = 4,
) -> Image.Image:
    """用高分辨率绘制后缩小，得到带半透明斜边的抗锯齿菱形。"""
    scale = max(2, int(oversample))
    border = max(1, int(outline_width))
    pad = border + 2
    width = max(3, int(math.ceil(half_width * 2 + pad * 2)))
    height = max(3, int(math.ceil(half_height * 2 + pad * 2)))
    hi_width = width * scale
    hi_height = height * scale
    center_x = hi_width / 2
    center_y = hi_height / 2
    hw = max(1.0, float(half_width)) * scale
    hh = max(1.0, float(half_height)) * scale
    points = [
        (center_x, center_y - hh),
        (center_x + hw, center_y),
        (center_x, center_y + hh),
        (center_x - hw, center_y),
    ]
    image = Image.new("RGBA", (hi_width, hi_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(
        points,
        fill=fill,
        outline=outline,
        width=max(1, border * scale),
    )
    return image.resize((width, height), Image.Resampling.LANCZOS)


class TimelineTrack:
    def __init__(self, parent_frame, app, track_data=None, default_name="默认轨道"):
        self.app = app
        self._default_name = default_name
        self.timeline_data = []
        self.current_next_node = None
        self.last_sound_alert_frame = -1
        self.is_flashing = False
        self._flash_after_id = None
        self._portrait_images = []  # 防止 PhotoImage 被垃圾回收
        self._node_image_cache = {}  # 抗锯齿菱形缓存，避免每帧重复生成

        self.mode = tk.StringVar(value="打轴模式")
        self.magnet_mode = tk.BooleanVar(value=True)
        self.magnet_locked = False  # 尺子时间流动时锁定吸附，禁止拖拽解除
        self._magnet_unlock_log_done = False  # 防止解锁日志在同一周期内重复输出
        self.track_zoom = 1.0  # 单轨道缩放比例
        self.sound_alert_enabled = tk.BooleanVar(value=True)
        self.visual_alert_enabled = tk.BooleanVar(value=True)
        # 总闸：本轨节点是否允许到点自动暂停（默认开）
        self.pause_enabled = tk.BooleanVar(
            value=bool(getattr(config, "PAUSE_ENABLED_DEFAULT", True))
        )
        self.alert_lead_frames = {"sound": 60, "visual": 60}
        self.alert_lead_var = tk.StringVar()
        self.alert_lead_var.set(str(self.alert_lead_frames["visual"]))
        self.alert_lead_var.trace_add("write", self._on_alert_lead_changed)

        self.name = default_name
        self.portrait_mgr = OperatorPortraitManager(self.app.scaling_factor)
        self._setup_ui(parent_frame)

        if track_data:
            self.load_data(track_data)

    def _setup_ui(self, parent):
        self.frame = ttk.Frame(parent, style="TFrame")
        self.frame.pack(fill=tk.X, expand=False, pady=1)
        self.frame.pack_propagate(False)

        # --- 标题栏 ---
        self.title_bar = ttk.Frame(self.frame, style="TFrame")
        self.title_bar.pack(fill=tk.X, side=tk.TOP)
        self.title_bar.bind("<Button-1>", lambda e: self.app.set_active_track(self))

        self.name_label = ttk.Label(self.title_bar, text=self.name, style="Info.TLabel",
                                    font=(config.FONT_FAMILY, self.app.scaled_font_normal, "bold"))
        self.name_label.pack(side=tk.LEFT, padx=(self.app.scaled_pad_m, 0))
        self.name_label.bind("<Button-1>", lambda e: self.app.set_active_track(self))
        self.name_label.bind("<Double-Button-1>", self._rename_track)

        self.mode_indicator = ttk.Label(self.title_bar, text="打轴", style="Info.TLabel")
        self.mode_indicator.pack(side=tk.LEFT, padx=self.app.scaled_pad_m)

        self.magnet_indicator = ttk.Label(self.title_bar, text="", style="Info.TLabel")
        self.magnet_indicator.pack(side=tk.LEFT, padx=self.app.scaled_pad_m)

        self.sound_indicator = ttk.Label(self.title_bar, text="", style="Info.TLabel")
        self.sound_indicator.pack(side=tk.LEFT, padx=self.app.scaled_pad_m)

        self.visual_indicator = ttk.Label(self.title_bar, text="", style="Info.TLabel")
        self.visual_indicator.pack(side=tk.LEFT, padx=self.app.scaled_pad_m)

        # --- Info frame（必须在 Canvas 之前 pack，否则 expand=True 的 Canvas 会抢占全部空间） ---
        self.info_frame = ttk.Frame(self.frame, style="TFrame")
        self.info_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.info_frame.columnconfigure(2, weight=1)  # 名称列自动扩展
        # 为预告列保留最小宽度，确保不会被前面的长名称完全挤出
        min_rem_width = max(80, int(60 * self.app.scaling_factor))
        self.info_frame.columnconfigure(5, minsize=min_rem_width)

        self.info_time_label = ttk.Label(self.info_frame, text="00:00:00", style="Info.TLabel",
                                         font=(config.FONT_FAMILY, self.app.scaled_font_large, "bold"))
        self.info_time_label.grid(row=0, column=0, sticky="w", padx=(self.app.scaled_pad_l, 0))

        self.info_diamond_label = ttk.Label(self.info_frame, text="", style="Info.TLabel")
        self.info_diamond_label.grid(row=0, column=1, sticky="w", padx=(self.app.scaled_pad_m, 0))

        self.info_name_label = ttk.Label(self.info_frame, text="", style="Info.TLabel", cursor="hand2",
                                         compound="left")
        self.info_name_label.grid(row=0, column=2, sticky="w", padx=(0, self.app.scaled_pad_m))
        self.info_name_label.bind("<Button-1>", self._on_node_name_click)

        # 节点跳转按钮
        self.prev_node_btn = ttk.Label(self.info_frame, text="◀", style="Info.TLabel", cursor="hand2")
        self.prev_node_btn.grid(row=0, column=3, sticky="e", padx=(0, self.app.scaled_pad_s))
        self.prev_node_btn.bind("<Button-1>", self._on_prev_node_click)

        self.next_node_btn = ttk.Label(self.info_frame, text="▶", style="Info.TLabel", cursor="hand2")
        self.next_node_btn.grid(row=0, column=4, sticky="e", padx=(0, self.app.scaled_pad_s))
        self.next_node_btn.bind("<Button-1>", self._on_next_node_click)

        self.info_remaining_label = ttk.Label(self.info_frame, text="", style="Info.TLabel")
        self.info_remaining_label.grid(row=0, column=5, sticky="e", padx=self.app.scaled_pad_m)

        # --- Canvas（最后 pack，expand=True 填满 title_bar 和 info_frame 之间的剩余空间） ---
        self.canvas = tk.Canvas(self.frame, bg="#21252b", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_drag_release)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)

    def _on_mouse_wheel(self, event):
        """光标位于轨道时，滚轮每格前后移动一个逻辑帧。"""
        delta = int(getattr(event, "delta", 0) or 0)
        button = getattr(event, "num", None)
        if delta > 0 or button == 4:
            direction = -1
        elif delta < 0 or button == 5:
            direction = 1
        else:
            return "break"
        self.app._move_timeline_by_frames(
            direction * config.MOUSE_WHEEL_SCROLL_STEP,
            track=self,
        )
        return "break"

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def load_data(self, data):
        self.name = data.get("name", self._default_name)
        self.name_label.config(text=self.name)
        self.mode.set(data.get("mode", "打轴模式"))
        self.magnet_mode.set(data.get("magnet_mode", True))
        self.sound_alert_enabled.set(data.get("sound_alert_enabled", True))
        self.visual_alert_enabled.set(data.get("visual_alert_enabled", True))
        self.alert_lead_frames["sound"] = data.get("alert_lead_frames", 60)
        self.alert_lead_frames["visual"] = data.get("alert_lead_frames", 60)
        self.alert_lead_var.set(str(self.alert_lead_frames["visual"]))
        self.pause_enabled.set(bool(data.get("pause_enabled", True)))
        raw_nodes = data.get("nodes", data.get("timeline_data", [])) or []
        # 节点补 pause_on_arrive 默认
        self.timeline_data = []
        for n in raw_nodes:
            if isinstance(n, dict):
                node = dict(n)
                node.setdefault("pause_on_arrive", True)
                self.timeline_data.append(node)
            else:
                self.timeline_data.append(n)

    def dump_data(self):
        return {
            "name": self.name,
            "mode": self.mode.get(),
            "magnet_mode": self.magnet_mode.get(),
            "sound_alert_enabled": self.sound_alert_enabled.get(),
            "visual_alert_enabled": self.visual_alert_enabled.get(),
            "alert_lead_frames": self.alert_lead_frames["visual"],
            "pause_enabled": bool(self.pause_enabled.get()),
            "nodes": copy.deepcopy(self.timeline_data)
        }

    def toggle_node_pause_at_cursor(self):
        """切换中心节点的 pause_on_arrive。"""
        node = self._find_node_at(self.get_center_frame(), tolerance=config.NODE_FIND_TOLERANCE)
        if not node:
            logger.info("切换节点暂停：中心处无节点")
            return
        cur = bool(node.get("pause_on_arrive", True))
        node["pause_on_arrive"] = not cur
        logger.info(
            "节点 '%s' 到点暂停 → %s",
            node.get("name"),
            "开" if node["pause_on_arrive"] else "关",
        )
        self.app._mark_dirty()
        try:
            self.update_display()
        except Exception:  # noqa: BLE001
            self.app._update_display()

    def rename_track_prompt(self, event=None):
        """按钮/菜单调用的轨道重命名。"""
        self._rename_track(event)

    def configure_node_at_cursor(self):
        """节点配置：名称 + 到点自动暂停。"""
        node = self._find_node_at(self.get_center_frame(), tolerance=config.NODE_FIND_TOLERANCE)
        if not node:
            # 打轴时若中心无节点，回退到「下一节点」便于对轴配置
            node = self.current_next_node
        if not node:
            logger.info("节点配置：附近无节点")
            try:
                from tkinter import messagebox
                messagebox.showinfo("节点配置", "请把中心线对准节点后再试。", parent=self.app.root)
            except Exception:  # noqa: BLE001
                pass
            return

        dlg = tk.Toplevel(self.app.root)
        dlg.title("节点配置")
        dlg.transient(self.app.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        try:
            dlg.configure(bg="#282c34")
        except tk.TclError:
            pass

        pad = max(6, int(self.app.scaled_pad_m * 2))
        frm = ttk.Frame(dlg, style="TFrame", padding=pad)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="名称:", style="Info.TLabel").grid(row=0, column=0, sticky="w", pady=pad)
        name_var = tk.StringVar(value=str(node.get("name", "")))
        name_entry = ttk.Entry(frm, textvariable=name_var, width=28)
        name_entry.grid(row=0, column=1, sticky="ew", pady=pad, padx=(pad, 0))
        name_entry.focus_set()
        name_entry.selection_range(0, tk.END)

        pause_var = tk.BooleanVar(value=bool(node.get("pause_on_arrive", True)))
        pause_chk = ttk.Checkbutton(
            frm,
            text="到点自动暂停（对轴模式）",
            variable=pause_var,
        )
        pause_chk.grid(row=1, column=0, columnspan=2, sticky="w", pady=pad)

        ttk.Label(
            frm,
            text=f"帧: {node.get('frame', '?')}",
            style="Info.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        btn_row = ttk.Frame(frm, style="TFrame")
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(pad, 0))

        def on_ok():
            new_name = name_var.get().strip()
            if new_name:
                old = node.get("name")
                node["name"] = new_name
                if old != new_name:
                    logger.info("节点 '%s' 重命名为 '%s'", old, new_name)
            node["pause_on_arrive"] = bool(pause_var.get())
            logger.info(
                "节点 '%s' 到点暂停=%s",
                node.get("name"),
                node["pause_on_arrive"],
            )
            self.app._mark_dirty()
            try:
                self.update_display()
            except Exception:  # noqa: BLE001
                self.app._update_display()
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=on_cancel, style="Tool.TButton").pack(
            side=tk.RIGHT, padx=(pad, 0)
        )
        ttk.Button(btn_row, text="确定", command=on_ok, style="Tool.TButton").pack(side=tk.RIGHT)
        dlg.bind("<Return>", lambda e: on_ok())
        dlg.bind("<Escape>", lambda e: on_cancel())

        dlg.update_idletasks()
        try:
            x = self.app.root.winfo_rootx() + 40
            y = self.app.root.winfo_rooty() + 40
            dlg.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    def set_height(self, height):
        """设置该轨道 widget 的目标总高度。"""
        self.frame.config(height=height)

    # ------------------------------------------------------------------
    # Core display
    # ------------------------------------------------------------------
    def get_center_frame(self):
        if self.magnet_mode.get():
            return self.app.current_game_frame
        return int(round(self.app.timeline_offset))

    def update_display(self):
        center_frame = self.get_center_frame()
        canvas = self.canvas
        canvas.delete("all")
        self._portrait_images.clear()
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or height <= 1:
            return

        pixels_per_frame = self.app.scaled_pixels_per_frame * self.track_zoom

        # 根据轨道 frame 高度计算紧凑级别
        track_h = self.frame.winfo_height()
        sf = self.app.scaling_factor
        if track_h < int(config.COMPACT_LEVEL_3_THRESHOLD * sf):
            compact_level = 3
        elif track_h < int(config.COMPACT_LEVEL_2_THRESHOLD * sf):
            compact_level = 2
        elif track_h < int(config.COMPACT_LEVEL_1_THRESHOLD * sf):
            compact_level = 1
        else:
            compact_level = 0

        self._draw_timeline_track(canvas, width, height)
        self._draw_timeline_ticks(canvas, center_frame, width, height, pixels_per_frame, compact_level)

        node_on_cursor = self._find_node_at(center_frame, tolerance=config.NODE_FIND_TOLERANCE)
        self._draw_nodes(canvas, center_frame, width, height, pixels_per_frame, node_on_cursor, compact_level)

        self._draw_playhead(canvas, center_frame, width, height, pixels_per_frame)
        self._draw_center_cursor(canvas, width, height)

        # Info panel
        self.info_time_label.config(text=format_frame_time(center_frame))
        self.current_next_node = self._find_next_node(center_frame)
        node_to_display = node_on_cursor if node_on_cursor else self.current_next_node

        if node_to_display:
            self.info_diamond_label.config(text=" ♦", foreground=node_to_display['color'])
            # 截断节点名称，避免 info_frame 中各列重叠
            display_name = self._truncate_node_name(node_to_display['name'])

            # compact_level >= 2 时，info_name_label 也支持头像替换
            if compact_level >= 2 and self.portrait_mgr:
                parsed_name, portrait_path = self.portrait_mgr.parse_name(display_name)
                if portrait_path:
                    photo = self.portrait_mgr.get_image(portrait_path)
                    if photo:
                        self._portrait_images.append(photo)
                        display_text = self._truncate_node_name(parsed_name)
                        self.info_name_label.config(
                            image=photo,
                            text=f" {display_text}({format_frame_time(node_to_display['frame'])})"
                        )
                    else:
                        self.info_name_label.config(
                            image="", text=f" {display_name}({format_frame_time(node_to_display['frame'])})"
                        )
                else:
                    self.info_name_label.config(
                        image="", text=f" {display_name}({format_frame_time(node_to_display['frame'])})"
                    )
            else:
                self.info_name_label.config(
                    image="", text=f" {display_name}({format_frame_time(node_to_display['frame'])})"
                )

            # 精确到帧才显示"现在"
            if node_on_cursor and node_on_cursor['frame'] == center_frame:
                self.info_remaining_label.config(text=" 现在", style="Now.Info.TLabel")
            else:
                # 预告：始终基于 current_next_node（真正的"下个节点"）
                next_node = self.current_next_node
                time_to_next = next_node['frame'] - center_frame if next_node else -1
                lead = self.alert_lead_frames["visual"]
                if (self.mode.get() == "对轴模式" and next_node and
                        0 < time_to_next <= lead):
                    self.info_remaining_label.config(
                        text=f"还剩{time_to_next}帧", style="Now.Info.TLabel"
                    )
                    logger.debug(f"[{self.name}] 节点预告: 还剩{time_to_next}帧")
                elif node_to_display:
                    time_to_next_display = node_to_display['frame'] - center_frame
                    self.info_remaining_label.config(text=f" {time_to_next_display}帧", style="Info.TLabel")
                else:
                    self.info_remaining_label.config(text="")
        else:
            self.info_diamond_label.config(text="")
            self.info_name_label.config(image="", text="")
            self.info_remaining_label.config(text="")

        # 标题栏状态指示
        self.mode_indicator.config(text="对轴" if self.mode.get() == "对轴模式" else "打轴")
        self.magnet_indicator.config(text="磁铁" if self.magnet_mode.get() else "")
        self.sound_indicator.config(text="🔊" if self.sound_alert_enabled.get() else "")
        self.visual_indicator.config(text="👁" if self.visual_alert_enabled.get() else "")
        # 轨道暂停总闸（对轴时有意义）
        pause_on = bool(self.pause_enabled.get()) if hasattr(self.pause_enabled, "get") else bool(self.pause_enabled)
        if not hasattr(self, "pause_indicator"):
            self.pause_indicator = ttk.Label(self.title_bar, text="", style="Info.TLabel")
            self.pause_indicator.pack(side=tk.LEFT, padx=self.app.scaled_pad_m)
        self.pause_indicator.config(text="⏸" if pause_on else "⏸×")

        # Alerts (only in 对轴模式)
        if self.mode.get() == "对轴模式" and self.current_next_node:
            time_to_alert = self.current_next_node['frame'] - center_frame
            self._handle_alerts(time_to_alert, self.current_next_node['frame'])
        else:
            self._handle_alerts(-1, -1)

        # 打轴模式下动态更新添加/删除按钮图标（由 app 负责，但这里提供状态）
        self.node_on_cursor = node_on_cursor

        # 节点跳转按钮状态：时间流逝时置灰禁用
        if self.app.is_time_flowing:
            self.prev_node_btn.config(foreground="#5c6370", cursor="")
            self.next_node_btn.config(foreground="#5c6370", cursor="")
        else:
            self.prev_node_btn.config(foreground="#abb2bf", cursor="hand2")
            self.next_node_btn.config(foreground="#abb2bf", cursor="hand2")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _draw_timeline_track(self, canvas, width, height):
        track_height = self.app.scaled_track_height
        y0 = (height - track_height) / 2
        y1 = (height + track_height) / 2
        canvas.create_rectangle(0, y0, width, y1, fill=config.TIMELINE_TRACK_COLOR, outline="")

    def _draw_timeline_ticks(self, canvas, center_frame, width, height, pixels_per_frame, compact_level=0):
        if pixels_per_frame <= 0:
            return
        frames_in_view = width / pixels_per_frame
        start_frame = int(center_frame - frames_in_view / 2)
        end_frame = int(center_frame + frames_in_view / 2)

        for frame in range(start_frame, end_frame + 1):
            if frame < 0:
                continue
            x_pos = width / 2 + (frame - center_frame) * pixels_per_frame

            if frame % config.FPS == 0:
                y0 = height / 2 - self.app.scaled_major_tick_h
                y1 = height / 2 + self.app.scaled_major_tick_h
                canvas.create_line(x_pos, y0, x_pos, y1, fill=config.TIMELINE_TICK_COLOR, width=2)
                # 紧凑级别 >= 1 时隐藏时间轴上方的时间文字
                if compact_level < 1:
                    time_str = f"{frame // (config.FPS * 60):02d}:{(frame // config.FPS) % 60:02d}"
                    canvas.create_text(x_pos, y0 - self.app.scaled_time_label_offset, text=time_str,
                                       fill=config.TIMELINE_TICK_COLOR,
                                       font=(config.FONT_FAMILY, self.app.scaled_font_normal),
                                       anchor="s")
            elif frame % config.TIMELINE_SUBTICK_INTERVAL == 0:
                y0 = height / 2 - self.app.scaled_minor_tick_h
                y1 = height / 2 + self.app.scaled_minor_tick_h
                canvas.create_line(x_pos, y0, x_pos, y1, fill=config.TIMELINE_SUBTICK_COLOR, width=1)

    def _get_node_diamond_photo(
        self,
        *,
        fill,
        outline,
        outline_width,
        half_width,
        half_height,
    ):
        key = (
            fill,
            outline,
            int(outline_width),
            round(float(half_width), 2),
            round(float(half_height), 2),
        )
        photo = self._node_image_cache.get(key)
        if photo is None:
            image = render_antialiased_diamond(
                fill=fill,
                outline=outline,
                outline_width=outline_width,
                half_width=half_width,
                half_height=half_height,
            )
            photo = ImageTk.PhotoImage(image)
            self._node_image_cache[key] = photo
        return photo

    def _draw_nodes(self, canvas, center_frame, width, height, pixels_per_frame, node_on_cursor, compact_level=0):
        # 1) 绘制所有菱形
        visible_nodes = []
        for node in self.timeline_data:
            frame_diff = node["frame"] - center_frame
            x_pos = width / 2 + frame_diff * pixels_per_frame
            if not (-self.app.scaled_node_diamond_w < x_pos < width + self.app.scaled_node_diamond_w):
                continue
            visible_nodes.append((node, x_pos))

        # 紧凑级别 >= 3 时减小菱形高度，避免上下顶点被遮挡
        diamond_scale = config.COMPACT_DIAMOND_SCALE if compact_level >= 3 else 1.0

        for node, x_pos in visible_nodes:
            scale = config.NODE_SELECTED_SCALE if node == node_on_cursor else 1.0
            outline_color = config.NODE_SELECTED_OUTLINE_COLOR if node == node_on_cursor else config.NODE_OUTLINE_COLOR
            outline_width = 2 if node == node_on_cursor else 1
            # 关闭「到点暂停」的节点用灰色轮廓区分
            if not bool(node.get("pause_on_arrive", True)):
                outline_color = "#888888"
                outline_width = max(outline_width, 2)

            h = self.app.scaled_node_diamond_h * scale * diamond_scale
            w = self.app.scaled_node_diamond_w * scale * diamond_scale
            photo = self._get_node_diamond_photo(
                fill=node["color"],
                outline=outline_color,
                outline_width=outline_width,
                half_width=w,
                half_height=h,
            )
            canvas.create_image(
                x_pos,
                height / 2,
                image=photo,
                tags=f"node_{node['frame']}",
            )
            if not bool(node.get("pause_on_arrive", True)):
                # 小标记：无暂停
                canvas.create_text(
                    x_pos, height / 2 - h - 2,
                    text="×", fill="#aaaaaa",
                    font=(config.FONT_FAMILY, max(7, self.app.scaled_font_normal)),
                    anchor="s",
                )

        # 2) 文字避让绘制
        # 紧凑级别 >= 2 时隐藏时间轴下方的节点名称
        if compact_level >= 2 or not visible_nodes:
            return

        try:
            fnt = font.Font(family=config.FONT_FAMILY, size=self.app.scaled_font_normal)
        except Exception:
            fnt = None

        padding = self.app.scaled_pad_s * 2

        # 排序：未经过节点优先，frame 小的优先
        visible_nodes.sort(key=lambda t: (0 if t[0]["frame"] >= center_frame else 1, t[0]["frame"]))

        occupied = []
        for node, x_pos in visible_nodes:
            raw_text = node["name"]
            display_text, portrait_path = self.portrait_mgr.parse_name(raw_text) if self.portrait_mgr else (raw_text, None)
            portrait_size = self.portrait_mgr.portrait_size if self.portrait_mgr else 0
            portrait_spacing = 4  # 头像与文字之间的间距

            # 计算文本宽度
            if fnt:
                text_w = fnt.measure(display_text) if display_text else 0
            else:
                text_w = len(display_text) * self.app.scaled_font_normal * 0.6 if display_text else 0

            # 总宽度 = 头像宽度(如有) + 间距 + 文字宽度
            total_w = text_w
            if portrait_path:
                total_w = portrait_size + portrait_spacing + text_w
            half_w = total_w / 2 + padding
            left, right = x_pos - half_w, x_pos + half_w

            # 检查是否超出画布边界
            if left < 0 or right > width:
                continue

            # 检查重叠
            overlap = False
            for occ_left, occ_right in occupied:
                if not (right < occ_left or left > occ_right):
                    overlap = True
                    break
            if overlap:
                continue

            h = self.app.scaled_node_diamond_h * (config.NODE_SELECTED_SCALE if node == node_on_cursor else 1.0)
            base_y = height / 2 + (h + self.app.scaled_node_name_offset)

            if portrait_path:
                photo = self.portrait_mgr.get_image(portrait_path)
                if photo:
                    self._portrait_images.append(photo)
                    # 头像 + 文字水平居中排列
                    # 总内容从 (x_pos - total_w/2) 到 (x_pos + total_w/2)
                    start_x = x_pos - total_w / 2
                    img_x = start_x + portrait_size / 2
                    # 头像中心与文字顶部齐平，允许向上覆盖时间轴
                    canvas.create_image(img_x, base_y, image=photo, anchor="center")
                    if display_text:
                        text_x = start_x + portrait_size + portrait_spacing + text_w / 2
                        canvas.create_text(text_x, base_y, text=display_text, fill="white",
                                           font=(config.FONT_FAMILY, self.app.scaled_font_normal),
                                           anchor="n")
                else:
                    # 头像加载失败，回退到纯文字
                    canvas.create_text(x_pos, base_y, text=raw_text, fill="white",
                                       font=(config.FONT_FAMILY, self.app.scaled_font_normal),
                                       anchor="n")
            else:
                canvas.create_text(x_pos, base_y, text=raw_text, fill="white",
                                   font=(config.FONT_FAMILY, self.app.scaled_font_normal),
                                   anchor="n")
            occupied.append((left, right))

    def _draw_playhead(self, canvas, center_frame, width, height, pixels_per_frame):
        playhead_x = width / 2 + (self.app.current_game_frame - center_frame) * pixels_per_frame
        if not (0 <= playhead_x <= width):
            return
        canvas.create_line(playhead_x, 0, playhead_x, height, fill="#ff6347", width=2, dash=(4, 2))
        ph = self.app.scaled_playhead_h
        pw = self.app.scaled_playhead_w
        canvas.create_polygon(playhead_x, ph, playhead_x - pw / 2, 0, playhead_x + pw / 2, 0,
                              fill='#ff6347', outline='')

    def _draw_center_cursor(self, canvas, width, height):
        center_x = width / 2
        canvas.create_line(center_x, 0, center_x, height, fill="#00FFFF", width=2)
        wing_len = self.app.scaled_cursor_wing
        canvas.create_line(center_x - wing_len, 0, center_x + wing_len, 0, fill="#00FFFF", width=2)
        canvas.create_line(center_x - wing_len, height, center_x + wing_len, height, fill="#00FFFF", width=2)

    # ------------------------------------------------------------------
    # Node logic
    # ------------------------------------------------------------------
    def _find_node_at(self, frame, tolerance=config.NODE_FIND_TOLERANCE):
        closest_node = None
        min_dist = float('inf')
        int_frame = int(round(frame))
        for node in self.timeline_data:
            dist = abs(node["frame"] - int_frame)
            if dist <= tolerance and dist < min_dist:
                min_dist = dist
                closest_node = node
        return closest_node

    def _find_next_node(self, from_frame):
        return next(
            (node for node in sorted(self.timeline_data, key=lambda x: x['frame']) if node['frame'] > from_frame),
            None
        )

    def add_or_remove_node_at_cursor(self):
        current_frame = self.get_center_frame()
        node_to_remove = self._find_node_at(current_frame, tolerance=config.NODE_FIND_TOLERANCE)
        if node_to_remove:
            self.timeline_data.remove(node_to_remove)
            logger.info(f"移除了节点: {node_to_remove['name']}")
            self.app._mark_dirty()
        else:
            new_node = {
                "frame": current_frame,
                "name": f"操作@{format_frame_time(current_frame)}",
                "color": config.NODE_COLORS[0],
                "pause_on_arrive": True,
            }
            self.timeline_data.append(new_node)
            logger.info(f"添加了新节点在 {current_frame} 帧")
            self.app._mark_dirty()

    def rename_node_at_cursor(self):
        self._rename_node_logic(
            self._find_node_at(self.get_center_frame(), tolerance=config.NODE_FIND_TOLERANCE)
        )

    def _rename_node_logic(self, node_to_rename):
        if not node_to_rename:
            return
        old_name = node_to_rename['name']
        new_name = simpledialog.askstring("重命名节点", "输入新名称:",
                                          initialvalue=node_to_rename.get('name', ''),
                                          parent=self.app.root)
        if new_name and new_name.strip():
            logger.info(f"节点 '{old_name}' 重命名为 '{new_name.strip()}'")
            node_to_rename['name'] = new_name.strip()
            self.app._mark_dirty()

    def change_node_color_at_cursor(self):
        node = self._find_node_at(self.get_center_frame(), tolerance=config.NODE_FIND_TOLERANCE)
        if not node:
            logger.info("切换颜色：中心处无节点（请把蓝线对准节点菱形）")
            return
        try:
            current_color_index = config.NODE_COLORS.index(node['color'])
            next_color_index = (current_color_index + 1) % len(config.NODE_COLORS)
            node['color'] = config.NODE_COLORS[next_color_index]
        except ValueError:
            node['color'] = config.NODE_COLORS[0]
        logger.info(f"节点 '{node['name']}' 颜色已更改为 {node['color']}")
        self.app._mark_dirty()
        # 立即重绘（否则要等下一帧 WS 推送才看得见）
        try:
            self.update_display()
        except Exception as e:  # noqa: BLE001
            logger.debug("颜色切换后重绘失败: %s", e)
            self.app._update_display()

    def _on_node_name_click(self, event):
        if self.mode.get() == "打轴模式":
            node_on_cursor = self._find_node_at(self.get_center_frame(), tolerance=config.NODE_FIND_TOLERANCE)
            node_to_rename = node_on_cursor if node_on_cursor else self.current_next_node
            if node_to_rename:
                self._rename_node_logic(node_to_rename)

    def _on_prev_node_click(self, event):
        """跳转到前一个最近的节点（忽略当前所在节点）。"""
        if self.app.is_time_flowing:
            return
        center_frame = self.get_center_frame()
        candidates = [node for node in self.timeline_data if node['frame'] < center_frame]
        if not candidates:
            return
        target = max(candidates, key=lambda n: n['frame'])
        self.app._animate_scroll_to(target['frame'])
        if self.magnet_mode.get():
            self.magnet_mode.set(False)
        logger.info(f"[{self.name}] 跳转到上一节点: {target['name']} @ {target['frame']}")

    def _on_next_node_click(self, event):
        """跳转到后一个最近的节点（忽略当前所在节点）。"""
        if self.app.is_time_flowing:
            return
        center_frame = self.get_center_frame()
        candidates = [node for node in self.timeline_data if node['frame'] > center_frame]
        if not candidates:
            return
        target = min(candidates, key=lambda n: n['frame'])
        self.app._animate_scroll_to(target['frame'])
        if self.magnet_mode.get():
            self.magnet_mode.set(False)
        logger.info(f"[{self.name}] 跳转到下一节点: {target['name']} @ {target['frame']}")

    @staticmethod
    def _truncate_node_name(name, max_chars=10):
        """截断节点名称，超过 max_chars 时添加省略号，防止 info_frame 各列重叠。"""
        if len(name) <= max_chars:
            return name
        return name[:max_chars - 1] + "…"

    def _on_alert_lead_changed(self, *args):
        try:
            frames_str = self.alert_lead_var.get()
            if frames_str:
                frames = int(frames_str)
                frames = max(0, min(frames, 300))
                self.alert_lead_frames["sound"] = frames
                self.alert_lead_frames["visual"] = frames
        except (ValueError, TclError):
            pass

    def _rename_track(self, event=None):
        new_name = simpledialog.askstring("重命名轨道", "输入新名称:",
                                          initialvalue=self.name,
                                          parent=self.app.root)
        if new_name and new_name.strip():
            self.name = new_name.strip()
            self.name_label.config(text=self.name)
            self.app._refresh_track_selector()
            self.app._mark_dirty()

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    def _handle_alerts(self, time_to_next, node_frame):
        try:
            import winsound
            HAS_WINSOUND = True
        except ImportError:
            HAS_WINSOUND = False

        if HAS_WINSOUND and self.sound_alert_enabled.get() and \
                0 < time_to_next <= self.alert_lead_frames["sound"] and \
                self.last_sound_alert_frame != node_frame:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ASYNC)
            self.last_sound_alert_frame = node_frame

        should_be_flashing = self.visual_alert_enabled.get() and 0 < time_to_next <= self.alert_lead_frames["visual"]

        if should_be_flashing and not self.is_flashing:
            self.is_flashing = True
            self._start_flash_loop()
        elif not should_be_flashing and self.is_flashing:
            self.is_flashing = False
            self._stop_flash_loop()

    def _start_flash_loop(self):
        """启动该轨道的独立闪烁循环（仅修改 canvas 背景）。"""
        if self._flash_after_id is not None:
            return
        self._flash_tick()

    def _stop_flash_loop(self):
        """停止闪烁并恢复 canvas 背景。"""
        if self._flash_after_id is not None:
            try:
                self.canvas.after_cancel(self._flash_after_id)
            except Exception:
                pass
            self._flash_after_id = None
        try:
            self.canvas.config(bg="#21252b")
        except tk.TclError:
            pass

    def _flash_tick(self):
        """闪烁一帧：在红/暗之间切换 canvas 背景。"""
        if not self.is_flashing:
            self._stop_flash_loop()
            return
        try:
            current = self.canvas.cget("bg")
            next_bg = "#5c2a2a" if current == "#21252b" else "#21252b"
            self.canvas.config(bg=next_bg)
            self._flash_after_id = self.canvas.after(250, self._flash_tick)
        except tk.TclError:
            self._flash_after_id = None

    # ------------------------------------------------------------------
    # Canvas drag events -> delegate to app
    # ------------------------------------------------------------------
    def _on_canvas_drag_start(self, event):
        self.app.on_timeline_drag_start(event)
        return "break"

    def _on_canvas_drag_motion(self, event):
        self.app.on_timeline_drag_motion(event, self)

    def _on_canvas_drag_release(self, event):
        self.app.on_timeline_drag_release(event, self)
