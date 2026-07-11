"""PendingPauseQueue 单元测试（纯逻辑，不依赖 tkinter / Win32）。"""
import unittest

from pause_queue import PauseGroup, PendingPauseQueue


def event(track_idx, frame, trigger_frame, name):
    """构造与 PauseEngine.tick 返回结构一致的事件字典。"""
    return {
        "track_idx": track_idx,
        "frame": frame,
        "trigger_frame": trigger_frame,
        "track_name": f"轨道{track_idx}",
        "name": name,
    }


class TestPendingPauseQueue(unittest.TestCase):
    def test_groups_same_trigger_frame_and_orders_distinct_frames(self):
        queue = PendingPauseQueue()
        queue.add([
            event(1, 271, 270, "B"),
            event(0, 268, 267, "A"),
            event(2, 271, 270, "C"),
        ])

        first = queue.pop()
        second = queue.pop()
        self.assertEqual(first.trigger_frame, 267)
        self.assertEqual([e["name"] for e in first.events], ["A"])
        self.assertEqual(second.trigger_frame, 270)
        self.assertEqual([e["name"] for e in second.events], ["B", "C"])
        self.assertIsNone(queue.pop())

    def test_deduplicates_same_track_and_node_frame(self):
        queue = PendingPauseQueue()
        duplicate = event(0, 60, 59, "A")
        queue.add([duplicate, dict(duplicate)])
        queue.add([dict(duplicate)])
        self.assertEqual(len(queue), 1)
        self.assertEqual(len(queue.peek().events), 1)

    def test_clear_removes_groups_and_dedup_keys(self):
        queue = PendingPauseQueue()
        item = event(0, 60, 59, "A")
        queue.add([item])
        queue.clear()
        queue.add([item])
        self.assertEqual(len(queue), 1)

    def test_add_returns_only_newly_added_groups(self):
        queue = PendingPauseQueue()
        added = queue.add([
            event(0, 268, 267, "A"),
            event(1, 271, 270, "B"),
        ])
        self.assertEqual({g.trigger_frame for g in added}, {267, 270})

        # 同 (track_idx, frame) 已存在，本次无新增
        again = queue.add([event(0, 268, 267, "A")])
        self.assertEqual(again, [])

    def test_pop_does_not_release_dedup_keys(self):
        queue = PendingPauseQueue()
        item = event(0, 60, 59, "A")
        queue.add([item])
        popped = queue.pop()
        self.assertIsNotNone(popped)
        self.assertEqual(len(queue), 0)

        # pop 后再次 add 同一 key，仍应被去重
        added = queue.add([item])
        self.assertEqual(added, [])
        self.assertEqual(len(queue), 0)

    def test_peek_does_not_remove_group(self):
        queue = PendingPauseQueue()
        queue.add([event(0, 60, 59, "A")])
        self.assertEqual(len(queue), 1)
        top = queue.peek()
        self.assertIsNotNone(top)
        self.assertEqual(top.trigger_frame, 59)
        # peek 不改变队列
        self.assertEqual(len(queue), 1)
        # 再次 peek 拿到同一对象
        self.assertIs(queue.peek(), top)

    def test_empty_queue_peek_and_pop_return_none(self):
        queue = PendingPauseQueue()
        self.assertIsNone(queue.peek())
        self.assertIsNone(queue.pop())
        self.assertEqual(len(queue), 0)

    def test_merge_into_existing_group_across_adds(self):
        queue = PendingPauseQueue()
        # 第一次 add 的 B 与第二次 add 的 C 同 trigger_frame=270，应合并成同一组
        queue.add([event(1, 271, 270, "B")])
        queue.add([event(2, 272, 270, "C")])
        # 仍只有一个 trigger=270 的组
        self.assertEqual(len(queue), 1)
        group = queue.peek()
        self.assertEqual(group.trigger_frame, 270)
        self.assertEqual([e["name"] for e in group.events], ["B", "C"])

    def test_pause_group_is_frozen(self):
        queue = PendingPauseQueue()
        queue.add([event(0, 60, 59, "A")])
        group = queue.peek()
        self.assertIsInstance(group, PauseGroup)
        # frozen dataclass：不可重新赋值属性
        with self.assertRaises(Exception):
            group.trigger_frame = 1  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
