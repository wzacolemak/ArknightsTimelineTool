"""费用尺多开检测的纯逻辑测试。"""
import unittest

from ruler_process import find_ruler_process_ids


class TestRulerProcessDetection(unittest.TestCase):
    def test_finds_ruler_processes_case_insensitively(self):
        entries = [
            (101, "ruler-app.exe"),
            (202, "Arknights.exe"),
            (303, "RULER-APP.EXE"),
        ]
        self.assertEqual(find_ruler_process_ids(entries=entries), [101, 303])

    def test_ignores_invalid_entries(self):
        entries = [(0, "ruler-app.exe"), (404, ""), (505, "other.exe")]
        self.assertEqual(find_ruler_process_ids(entries=entries), [])


if __name__ == "__main__":
    unittest.main()
