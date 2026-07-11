# --- 项目信息 ---
VERSION = "TimelineTool_独立版_20260711"

# --- 应用设置 ---
FPS = 30
NODE_COLORS = ["#ff6347", "#4682b4", "#32cd32", "#ffd700", "#9370db", "#ffa500"]
WINDOW_WIDTH = 500
WINDOW_HEIGHT = WINDOW_WIDTH // 5
MIN_WINDOW_HEIGHT = 100
DEFAULT_ALPHA = 0.85
ICON_SIZE = (15, 15)

# --- 多轨道与高度 ---
TRACK_TITLE_HEIGHT = 18
TRACK_INFO_HEIGHT = 22
RESIZE_HANDLE_HEIGHT = 6
TRACK_MIN_HEIGHT = 50
NODE_LABEL_MIN_GAP = 4

# --- 时间轴与节点 ---
PIXELS_PER_FRAME = 2            # 每个逻辑帧在时间轴上占用的像素

NODE_FIND_TOLERANCE = 3         # 光标附近查找节点的容差（帧）
NODE_CLICK_TOLERANCE = 15       # 点击节点的容差范围（帧），比查找范围大更易于点击
NODE_DIAMOND_SIZE = {"h": 6, "w": 3.5} # 略小的抗锯齿节点菱形半高/半宽
NODE_OUTLINE_COLOR = "#FFFFFF"  # 节点默认轮廓颜色
NODE_SELECTED_OUTLINE_COLOR = "#00FFFF" # 选中时节点的高亮轮廓颜色
NODE_SELECTED_SCALE = 1.5       # 选中时节点的放大倍数

# --- 交互手感 ---
TIMELINE_DRAG_SENSITIVITY = 2   # 时间轴拖动灵敏度，分母越小越灵敏
MAGNET_BREAK_THRESHOLD = 30     # 在磁铁模式下拖动超过多少像素时自动关闭磁铁模式
INERTIA_FRICTION = 0.2         # 惯性滚动的摩擦力，越接近1滚动越远
DRAG_START_THRESHOLD = 5          # 拖动超过多少像素才算开始拖拽
MIN_ZOOM = 0.2                  # 最小缩放比例
MAX_ZOOM = 5.0                  # 最大缩放比例
KEYBOARD_SCROLL_STEP = 1        # 键盘左右键细调：每次移动 1 逻辑帧
MOUSE_WHEEL_SCROLL_STEP = 10    # 轨道滚轮粗调：每格移动 10 逻辑帧

# --- 时间轴视觉 ---
TIMELINE_TRACK_COLOR = "#2c313a" # 时间轴轨道的背景色
TIMELINE_TRACK_HEIGHT = 40      # 时间轴轨道的高度（像素）
TIMELINE_TICK_COLOR = "#abb2bf"  # 时间刻度线（秒）的主颜色
TIMELINE_SUBTICK_COLOR = "#5c6370" # 时间刻度线（帧）的次颜色
TIMELINE_MAJOR_TICK_H = 10      # 秒级刻度线半高
TIMELINE_MINOR_TICK_H = 4       # 帧级刻度线半高
TIMELINE_SUBTICK_INTERVAL = 10  # 每隔多少帧画一个子刻度线
TIMELINE_TIME_LABEL_OFFSET_Y = 10 # 时间文字距离刻度线上方的距离
NODE_NAME_LABEL_OFFSET_Y = 10     # 节点名称距离菱形下方的距离
PLAYHEAD_TRIANGLE_HEIGHT = 8      # 播放头三角形的高度
PLAYHEAD_TRIANGLE_WIDTH = 6       # 播放头三角形的宽度
CENTER_CURSOR_WING_LENGTH = 8     # 中心光标“翅膀”的长度

# --- 布局与字体 ---
FONT_FAMILY = "Segoe UI" # 字体家族
# 字体大小
FONT_SIZE_NORMAL = -9
FONT_SIZE_LARGE = -18
# 边距与间距
PADDING_XS = 0
PADDING_S = 2
PADDING_M = 3
PADDING_L = 5
PADDING_XL = 10
# 按钮与控件
TOOL_BUTTON_PADDING = 0



# --- 紧凑级别阈值（基于单个轨道 frame 高度，乘以缩放因子后的像素值） ---
COMPACT_LEVEL_1_THRESHOLD = 105  # 隐藏时间轴上方时间文字
COMPACT_LEVEL_2_THRESHOLD = 85   # 隐藏时间轴下方节点名称，info_name 支持头像
COMPACT_LEVEL_3_THRESHOLD = 70   # 减小菱形高度
COMPACT_DIAMOND_SCALE = 0.5      # 阶段3菱形缩放比例

# --- 网络设置 ---
# 最新 Rust 费用尺绑定 127.0.0.1:2606；localhost 亦可。
WEBSOCKET_URI = "ws://127.0.0.1:2606"
WEBSOCKET_RECONNECT_DELAY = 5
QUEUE_POLL_INTERVAL = 16 # ~60 FPS
RULER_PROCESS_CHECK_INTERVAL_MS = 5000  # 周期检测 ruler-app 多开

# --- 自动暂停（到点发键）---
# PC 客户端固定使用 ESC + SendInput；不自动发送 Space 恢复 PC 游戏。
PC_PAUSE_HOTKEY = "Escape"       # PC 客户端暂停键（固定 ESC）
PC_PAUSE_KEY_HOLD_MS = 50        # SendInput key-down 保持时长（毫秒）
FOCUS_GAME_BEFORE_SEND = True    # 目标不在前台时尝试 Seize 抢前台后再 SendInput
PAUSE_ENABLED_DEFAULT = True     # 新轨道/节点默认允许暂停
# PC 客户端（非 ADB）发键时是否要求管理员；非管理员只警告，仍尝试发键。
PAUSE_REQUIRE_ADMIN_FOR_PC = True
# 提前发键（补偿输入延迟）。与轴/费用尺同一套「逻辑帧」，
# 与显示器刷新率 60/90/120/144 无关。
# UI「暂停提前(帧)」会覆盖 PAUSE_LEAD_FRAMES；None 时用 PAUSE_LEAD_MS 换算。
PAUSE_LEAD_FRAMES = 1            # 默认提前 1 逻辑帧；0=到点再发
PAUSE_LEAD_MS = 30               # 仅当 PAUSE_LEAD_FRAMES is None 时启用
LOGIC_FPS = FPS                  # 逻辑帧率，与时间轴 FPS 一致
# 发键后校验：以费用尺帧是否真正停住为准（API 返回成功≠游戏吃键）。
# 不同 trigger_frame 的相邻节点逐次暂停；校验失败由上层状态机处理。
PAUSE_VERIFY_TIMEOUT_SEC = 0.45
PAUSE_VERIFY_STALL_UPDATES = 3   # 连续多少次快照帧未增加才进入「疑似停」
PAUSE_GATE_MIN_STALL_SEC = 0.18  # 疑似停后再撑过该时长 → 确认 frozen（防单帧抖动）
PAUSE_VERIFY_FAIL_ADVANCE = 6    # 相对发键时前进超过该逻辑帧仍未确认停 → 视为失败
PAUSE_SETTINGS_FILE = "pause_settings.json"  # 持久化 UI 里的暂停提前帧
# 标题关键字（大小写不敏感子串）；点选绑定优先于关键字。
GAME_WINDOW_TITLE_KEYWORDS = [
    "明日方舟",
    "Arknights",
    "MuMu",
    "雷电",
    "LDPlayer",
    "夜神",
    "Nox",
    "BlueStacks",
]
BOUND_WINDOW_FILE = "bound_game_window.json"  # 相对项目根 / exe 同级

# --- ADB 暂停（MuMu / 雷电等模拟器的独立路径，不是 PC 失败回退）---
# 模拟器通过 adb shell input keyevent 发送 Space。该路径与 PC ESC + SendInput
# 完全独立：PC 路径失败不会自动改走 ADB。
ADB_PAUSE_HOTKEY = "Space"   # 模拟器暂停键
ADB_PAUSE_ENABLED = True
ADB_SERIAL = ""              # 空=自动选第一台 device；可填 127.0.0.1:16384 等
ADB_KEYEVENT = 62            # KEYCODE_SPACE；也可被 ADB_PAUSE_HOTKEY 映射覆盖
# 绑定窗标题含模拟器关键字时优先走 ADB
ADB_PREFER_FOR_EMULATOR = True

# --- 日志和资源目录 ---
LOG_DIR = "logs"
ICON_DIR = "icons"
