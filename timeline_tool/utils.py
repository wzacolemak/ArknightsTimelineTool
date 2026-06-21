import sys
import os
import logging
import datetime
from config import LOG_DIR, FPS

def resource_path(relative_path: str) -> str:
    """
    获取资源的绝对路径，无论是从源码运行还是从打包后的exe运行。
    """
    try:
        # PyInstaller 创建一个临时文件夹，并把路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    except Exception:
        # 在开发模式下：
        # 1. os.path.abspath(__file__) 获取当前文件(utils.py)的绝对路径
        # 2. os.path.dirname(...) 获取该文件所在的目录 (ruler/)
        # 3. 再用一次 os.path.dirname(...) 返回上一级目录，即项目根目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(script_dir) if os.path.basename(script_dir) == "timeline_tool" else script_dir

    return os.path.join(base_path, relative_path)

def _get_log_dir():
    """
    获取日志目录的绝对路径。
    注意：日志是持久化输出，不能放在 PyInstaller 的 _MEIPASS 临时目录中，
    否则程序退出后日志会被 bootloader 清理掉。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 模式：日志保存在 exe 同级目录
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, LOG_DIR)
    else:
        # 开发模式：日志保存在项目根目录（与 utils.py 平级的上级目录）
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(script_dir) if os.path.basename(script_dir) == "timeline_tool" else script_dir
        return os.path.join(base_path, LOG_DIR)


# --- 日志系统 ---
def setup_logging(debug_image_mode=False):
    """
    配置全局日志记录器。
    """
    # 在未来的扩展中使用
    IMG_DUMP_DIR = ""
    DEBUG_IMAGE_MODE = debug_image_mode

    # 创建日志目录（持久化输出，不能放在 _MEIPASS 临时目录）
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    if DEBUG_IMAGE_MODE:
        IMG_DUMP_DIR = os.path.join(log_dir, "img_dumps")
        os.makedirs(IMG_DUMP_DIR, exist_ok=True)

    # 定义日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)-25s - %(levelname)-8s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # --- 文件处理器 ---
    log_filename = f"run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_filepath = os.path.join(log_dir, log_filename)
    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # --- 控制台处理器 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 调整日志级别：根记录器 INFO，第三方库 WARNING，本项目 DEBUG
    root_logger.setLevel(logging.INFO)
    logging.getLogger("timeline_tool").setLevel(logging.DEBUG)
    for third_party in ("websockets", "urllib3", "PIL"):
        logging.getLogger(third_party).setLevel(logging.WARNING)

    initial_log = logging.getLogger("LoggerSetup")
    initial_log.info("=" * 60)
    initial_log.info("日志系统已初始化。")
    initial_log.info(f"日志文件将保存在: {os.path.abspath(log_filepath)}")
    if DEBUG_IMAGE_MODE:
        initial_log.info(f"调试图像将保存在: {os.path.abspath(IMG_DUMP_DIR)}")

# --- 通用工具函数 ---
def format_frame_time(total_frames):
    """将总帧数格式化为 MM:SS:FF 格式"""
    if not isinstance(total_frames, int) or total_frames < 0:
        return "--:--:--"
    total_seconds = total_frames // FPS
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    frames = total_frames % FPS
    return f"{minutes:02d}:{seconds:02d}:{frames:02d}"
