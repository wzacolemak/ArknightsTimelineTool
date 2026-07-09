"""到点自动暂停：帧边沿检测 + 去重。纯逻辑，不依赖 tkinter / Win32。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# totalElapsedFrames 回退超过此阈值视为计时器重置，清空去重。
AUTO_RESET_THRESHOLD = 30

# (track_idx, node_frame)
FiredKey = Tuple[int, int]


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    return bool(value)


def is_replay_mode(mode: Any) -> bool:
    """对轴模式（兼容中英文/枚举字符串）。"""
    if mode is None:
        return False
    s = str(mode).strip().lower()
    return s in {"对轴模式", "对轴", "replay", "following", "follow"}


def normalize_node(node: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(node)
    out.setdefault("pause_on_arrive", True)
    return out


def normalize_track(track: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(track)
    out.setdefault("pause_enabled", True)
    nodes = out.get("nodes", out.get("timeline_data", [])) or []
    out["nodes"] = [normalize_node(n) if isinstance(n, dict) else n for n in nodes]
    return out


class PauseEngine:
    """根据相邻两帧与轨道数据，决定是否应对哪些节点触发暂停。"""

    def __init__(self, reset_threshold: int = AUTO_RESET_THRESHOLD):
        self.reset_threshold = reset_threshold
        self._last_frame: Optional[int] = None
        self._fired: Set[FiredKey] = set()

    def reset(self) -> None:
        self._last_frame = None
        self._fired.clear()

    @property
    def last_frame(self) -> Optional[int]:
        return self._last_frame

    def tick(
        self,
        current_frame: int,
        tracks: Iterable[Any],
        *,
        is_running: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        返回本 tick 应触发暂停的事件列表。
        每项: {track_idx, frame, name, track_name}
        """
        if not is_running:
            self._last_frame = current_frame
            return []

        if self._last_frame is None:
            self._last_frame = current_frame
            return []

        last = self._last_frame
        # 大幅回退 = 自动/手动重置计时
        if current_frame + self.reset_threshold < last:
            logger.info(
                "检测到帧回退 %s → %s，清空暂停去重表",
                last,
                current_frame,
            )
            self._fired.clear()
            self._last_frame = current_frame
            return []

        events: List[Dict[str, Any]] = []
        if current_frame <= last:
            # 未前进：不触发（暂停中或卡帧）
            self._last_frame = current_frame
            return []

        for t_idx, track in enumerate(tracks):
            track_dict = self._track_as_dict(track)
            if not is_replay_mode(track_dict.get("mode")):
                continue
            if not _truthy(track_dict.get("pause_enabled"), True):
                continue
            track_name = track_dict.get("name", f"轨道{t_idx}")
            for node in track_dict.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                if not _truthy(node.get("pause_on_arrive"), True):
                    continue
                frame = node.get("frame")
                if frame is None:
                    continue
                try:
                    frame_i = int(frame)
                except (TypeError, ValueError):
                    continue
                if not (last < frame_i <= current_frame):
                    continue
                key: FiredKey = (t_idx, frame_i)
                if key in self._fired:
                    continue
                self._fired.add(key)
                events.append(
                    {
                        "track_idx": t_idx,
                        "frame": frame_i,
                        "name": str(node.get("name", "")),
                        "track_name": str(track_name),
                    }
                )

        self._last_frame = current_frame
        return events

    @staticmethod
    def _track_as_dict(track: Any) -> Dict[str, Any]:
        """支持 dict 或带 dump_data / 属性的 TimelineTrack 对象。"""
        if isinstance(track, dict):
            return normalize_track(track)
        # TimelineTrack 对象
        mode = track.mode.get() if hasattr(track.mode, "get") else getattr(track, "mode", "")
        nodes = getattr(track, "timeline_data", None)
        if nodes is None and hasattr(track, "dump_data"):
            dumped = track.dump_data()
            return normalize_track(dumped)
        return normalize_track(
            {
                "name": getattr(track, "name", ""),
                "mode": mode,
                "pause_enabled": getattr(track, "pause_enabled", True),
                "nodes": nodes or [],
            }
        )
