"""相邻自动暂停节点的排序、同帧合并与去重队列。纯逻辑，不依赖 tkinter / Win32。

Python 3.8 兼容：使用 ``typing`` 显式 import，不使用 3.9+ 的 ``list``/``dict``/``tuple``
内置泛型语法，也不使用 ``X | Y`` 联合类型语法。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

Event = Dict[str, Any]
EventKey = Tuple[int, int]


@dataclass(frozen=True)
class PauseGroup:
    """同一 ``trigger_frame`` 的若干暂停事件合并成的一组。"""

    trigger_frame: int
    events: Tuple[Event, ...]


class PendingPauseQueue:
    """消费 PauseEngine 事件，按 ``trigger_frame`` 升序排序、同帧合并、按节点去重。

    - 不同 ``trigger_frame`` 按数字升序排列。
    - 相同 ``trigger_frame`` 合并成一个 :class:`PauseGroup`，组内保持首次出现顺序。
    - 同一 ``(track_idx, frame)`` 只能加入一次；``pop()`` 不会释放该去重 key，
      只有 :meth:`clear` 同时清空组和去重 key。
    """

    def __init__(self) -> None:
        self._groups: List[PauseGroup] = []
        self._keys: Set[EventKey] = set()

    def add(self, events: Iterable[Event]) -> List[PauseGroup]:
        """将一批事件加入队列，返回本次实际新增的 groups（按 trigger_frame 升序）。

        去重按 ``(track_idx, frame)``；已存在的 key 直接跳过，不会进入任何 group。
        新增事件可能与既有 group 合并到同一 ``trigger_frame``；此时返回的对应 group
        只包含本次新增的事件，既有 group 在队列中保持原首次出现顺序。
        """
        by_trigger: Dict[int, List[Event]] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            try:
                key: EventKey = (int(event["track_idx"]), int(event["frame"]))
            except (KeyError, TypeError, ValueError):
                continue
            if key in self._keys:
                continue
            self._keys.add(key)
            try:
                trigger = int(event.get("trigger_frame", event["frame"]))
            except (TypeError, ValueError):
                trigger = int(event["frame"])
            by_trigger.setdefault(trigger, []).append(dict(event))

        added: List[PauseGroup] = [
            PauseGroup(trigger, tuple(group_events))
            for trigger, group_events in sorted(by_trigger.items())
        ]
        self._rebuild_with(added)
        return added

    def _rebuild_with(self, added: Iterable[PauseGroup]) -> None:
        """合并既有 groups 与新增 groups，保持按 trigger_frame 升序、组内首次出现顺序。"""
        combined: Dict[int, List[Event]] = {}
        for group in [*self._groups, *added]:
            combined.setdefault(group.trigger_frame, []).extend(group.events)
        self._groups = [
            PauseGroup(trigger, tuple(events))
            for trigger, events in sorted(combined.items())
        ]

    def peek(self) -> Optional[PauseGroup]:
        """返回队首 group 但不移除；队列为空时返回 ``None``。"""
        return self._groups[0] if self._groups else None

    def pop(self) -> Optional[PauseGroup]:
        """移除并返回队首 group；队列为空时返回 ``None``。

        注意：``pop`` 不会释放去重 key，因此已被消费的事件不会再次入队。
        """
        return self._groups.pop(0) if self._groups else None

    def clear(self) -> None:
        """清空所有 groups 与去重 key。"""
        self._groups.clear()
        self._keys.clear()

    def __len__(self) -> int:
        return len(self._groups)
