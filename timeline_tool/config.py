# --- 项目信息 ---
VERSION = "TimelineTool_卓越特供版_20260601"

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
NODE_DIAMOND_SIZE = {"h": 7, "w": 4} # 节点菱形的大小
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
KEYBOARD_SCROLL_STEP = 30       # 键盘左右键移动时间轴的步进（帧）

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
WEBSOCKET_URI = "ws://localhost:2606"
WEBSOCKET_RECONNECT_DELAY = 5
QUEUE_POLL_INTERVAL = 16 # ~60 FPS

# --- 日志和资源目录 ---
LOG_DIR = "logs"
ICON_DIR = "icons"
