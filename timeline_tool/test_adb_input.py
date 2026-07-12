import os
import sys
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adb_input


class TestAdbPauseTap(unittest.TestCase):
    def test_pause_tap_uses_maa_region_center_at_1280x720(self):
        with patch("adb_input.find_adb", return_value="adb.exe"), \
             patch("adb_input.pick_serial", return_value="127.0.0.1:7555"), \
             patch(
                 "adb_input._run",
                 side_effect=[
                     (0, "Physical size: 1280x720", ""),
                     (0, "", ""),
                 ],
             ) as run:
            point = adb_input.send_pause_tap()

        self.assertEqual(point, (1200, 50))
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["adb.exe", "-s", "127.0.0.1:7555", "shell", "wm", "size"],
                    timeout=5.0,
                ),
                call(
                    [
                        "adb.exe", "-s", "127.0.0.1:7555", "shell",
                        "input", "tap", "1200", "50",
                    ],
                    timeout=5.0,
                ),
            ],
        )

    def test_pause_tap_scales_to_1920x1080_override_size(self):
        with patch("adb_input.find_adb", return_value="adb.exe"), \
             patch("adb_input.pick_serial", return_value="emulator-5554"), \
             patch(
                 "adb_input._run",
                 side_effect=[
                     (
                         0,
                         "Physical size: 2560x1440\nOverride size: 1920x1080",
                         "",
                     ),
                     (0, "", ""),
                 ],
             ):
            point = adb_input.send_pause_tap()

        self.assertEqual(point, (1800, 75))

    def test_pause_tap_raises_when_adb_tap_fails(self):
        with patch("adb_input.find_adb", return_value="adb.exe"), \
             patch("adb_input.pick_serial", return_value="emulator-5554"), \
             patch(
                 "adb_input._run",
                 side_effect=[
                     (0, "Physical size: 1280x720", ""),
                     (1, "", "device offline"),
                 ],
             ):
            with self.assertRaisesRegex(OSError, "ADB 点击暂停失败"):
                adb_input.send_pause_tap()


class TestEmulatorWindowDetection(unittest.TestCase):
    def test_detects_mumu_window(self):
        self.assertTrue(
            adb_input.looks_like_emulator_window(
                "MuMu模拟器12", "Qt5152QWindowOwnDC"
            )
        )

    def test_detects_ldplayer_window(self):
        self.assertTrue(
            adb_input.looks_like_emulator_window(
                "雷电模拟器", "LDPlayerMainFrame"
            )
        )


class TestAdbDeviceSelection(unittest.TestCase):
    def test_multiple_devices_require_explicit_serial(self):
        adb_input._cached_serial = None
        with patch("adb_input.find_adb", return_value="adb.exe"), \
             patch("adb_input.list_devices", return_value=["device-a", "device-b"]):
            self.assertIsNone(adb_input.pick_serial(adb_path="adb.exe"))

    def test_single_device_is_selected_automatically(self):
        adb_input._cached_serial = None
        with patch("adb_input.find_adb", return_value="adb.exe"), \
             patch("adb_input.list_devices", return_value=["device-a"]):
            self.assertEqual(adb_input.pick_serial(adb_path="adb.exe"), "device-a")


if __name__ == "__main__":
    unittest.main()
