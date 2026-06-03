import os
import sys


def get_base_dir() -> str:
    """
    获取应用的基础目录。
    - 打包后（PyInstaller）：返回 exe 所在目录。
    - 开发模式：返回项目根目录（当前文件所在目录的上一级）。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，sys.executable 指向 exe 文件
        return os.path.dirname(sys.executable)
    else:
        # 开发模式：path_helper.py 位于 ruler/ 下，上级即为项目根目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(script_dir)


def get_external_path(relative_path: str) -> str:
    """
    获取外部数据文件的绝对路径。
    用于用户可修改的文件，如 config.json、calibration/、logs/ 等。
    """
    return os.path.join(get_base_dir(), relative_path)


def get_internal_resource_path(relative_path: str) -> str:
    """
    获取内部资源文件的绝对路径。
    用于打包进 exe 的只读资源，如 icons/。
    PyInstaller 运行时会从 sys._MEIPASS 读取；开发模式则从项目根目录读取。
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(script_dir)
    return os.path.join(base_path, relative_path)
