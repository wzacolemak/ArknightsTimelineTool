"""窗口绑定的安全回归测试。"""
import unittest
from unittest.mock import patch

from game_window import BoundWindow, refresh_bound_hwnd


class TestBoundWindowRefresh(unittest.TestCase):
    def test_missing_emulator_binding_does_not_fall_back_to_pc_client(self):
        """模拟器绑定失效时，绝不能静默改绑到正在运行的 PC 客户端。"""
        bound = BoundWindow(title="MuMu模拟器", class_name="QtWindow", hwnd=42)
        pc_window = {
            "hwnd": 99,
            "title": "明日方舟",
            "class_name": "UnityWndClass",
        }

        with patch("game_window.find_bound", return_value=None), patch(
            "game_window.find_maa_pc_client", return_value=pc_window
        ):
            updated, window = refresh_bound_hwnd(bound)

        self.assertEqual(updated, bound)
        self.assertIsNone(window)


if __name__ == "__main__":
    unittest.main()
