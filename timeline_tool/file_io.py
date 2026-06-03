import json
import logging
from datetime import datetime
from tkinter import filedialog, messagebox

logger = logging.getLogger(__name__)

def _normalize_track_data(track):
    """确保轨道数据包含所有必要字段，填充默认值。"""
    return {
        "name": track.get("name", "默认轨道"),
        "mode": track.get("mode", "打轴模式"),
        "magnet_mode": track.get("magnet_mode", True),
        "sound_alert_enabled": track.get("sound_alert_enabled", True),
        "visual_alert_enabled": track.get("visual_alert_enabled", True),
        "alert_lead_frames": track.get("alert_lead_frames", 60),
        "nodes": track.get("nodes", track.get("timeline_data", []))
    }

def _load_from_path(filepath):
    """从指定路径读取并解析时间轴 JSON（不弹对话框）。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # 兼容旧版：纯列表视为单轨道
    if isinstance(raw, list):
        data = {
            "version": "2.0",
            "tracks": [_normalize_track_data({"nodes": raw})]
        }
    elif isinstance(raw, dict) and "tracks" in raw:
        data = {
            "version": raw.get("version", "2.0"),
            "tracks": [_normalize_track_data(t) for t in raw["tracks"]]
        }
    else:
        # 尝试把 dict 的 key 当作单轨道（老格式意外情况）
        data = {
            "version": "2.0",
            "tracks": [_normalize_track_data({"nodes": raw if isinstance(raw, list) else []})]
        }
    return data


def load_timeline_from_file(parent_widget):
    """
    打开文件对话框以加载时间轴JSON文件。
    返回 (标准化的多轨道数据 dict, 文件路径) 或 (None, None)。
    兼容旧版纯节点列表格式。
    """
    filepath = filedialog.askopenfilename(
        title="打开时间轴文件",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        parent=parent_widget
    )
    if not filepath:
        return None, None
    try:
        data = _load_from_path(filepath)
        logger.info(f"成功加载时间轴: {filepath}")
        return data, filepath
    except Exception as e:
        logger.error(f"加载文件失败: {filepath}，错误: {e}")
        messagebox.showerror("加载失败", f"无法加载或解析文件: \n{e}", parent=parent_widget)
        return None, None

def save_timeline_to_file(tracks_data, parent_widget, initialfile=None):
    """
    打开文件对话框以保存多轨道时间轴数据到JSON文件。
    tracks_data: list[dict]，每个 dict 包含轨道的全部状态和 nodes 列表。
    initialfile: 可选，自定义默认文件名（不含扩展名）。
    返回 (是否成功, 文件路径)。
    """
    if initialfile is None:
        now = datetime.now()
        track_count = len(tracks_data)
        initialfile = f"#{now:%m%d%H%M}_{track_count}o"
    filepath = filedialog.asksaveasfilename(
        title="保存时间轴文件",
        defaultextension=".json",
        initialfile=initialfile,
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        parent=parent_widget
    )
    if not filepath:
        return False, None
    payload = {
        "version": "2.0",
        "tracks": tracks_data
    }
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        logger.info(f"成功保存时间轴: {filepath}")
        return True, filepath
    except Exception as e:
        logger.error(f"保存文件失败: {filepath}，错误: {e}")
        messagebox.showerror("保存失败", f"无法写入文件: \n{e}", parent=parent_widget)
        return False, None
