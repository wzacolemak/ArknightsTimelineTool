import json
import logging
import os
import sys
from datetime import datetime

from utils import resource_path

logger = logging.getLogger(__name__)


def _get_config_path():
    """优先从 exe 同级目录读取 naming_config.json，回退到打包内部路径。"""
    if getattr(sys, 'frozen', False):
        external_path = os.path.join(os.path.dirname(sys.executable), "naming_config.json")
    else:
        external_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "naming_config.json"
        )
    if os.path.exists(external_path):
        return external_path
    return resource_path(os.path.join("timeline_tool", "naming_config.json"))


class NamingManager:
    """管理保存时的规范化命名配置，支持多预设。"""

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self):
        try:
            with open(_get_config_path(), 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"命名配置文件加载失败: {e}，使用默认配置（禁用）。")
            return {"enabled": False, "default_preset": "", "presets": []}

    def is_enabled(self):
        return self._config.get("enabled", False)

    def get_default_preset(self):
        """返回默认 preset 名称。"""
        return self._config.get("default_preset", "")

    def get_presets(self):
        """返回所有预设名称列表。"""
        return [p["name"] for p in self._config.get("presets", [])]

    def get_preset_fields(self, preset_name):
        """返回指定预设的字段定义列表。"""
        for p in self._config.get("presets", []):
            if p["name"] == preset_name:
                return p.get("fields", [])
        return []

    def get_all_presets(self):
        """返回完整预设列表（含 name 和 fields）。"""
        return self._config.get("presets", [])

    def build_filename(self, values, track_count):
        """根据填写的值和轨道数合成文件名（不含扩展名）。"""
        parts = []
        for val in values.values():
            val = val.strip()
            if val:
                parts.append(val)
        return "_".join(parts) if parts else "untitled"
