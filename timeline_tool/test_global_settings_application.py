import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
import config
import hotkey_send
from emulator_detector import AdbDetectionResult
from settings_manager import default_settings


class FakeVar:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class TestGlobalSettingsApplication(unittest.TestCase):
    def test_apply_updates_runtime_safe_values_and_rebinds(self):
        original_config = {
            name: getattr(config, name)
            for name in (
                "NODE_FIND_TOLERANCE", "NODE_CLICK_TOLERANCE",
                "KEYBOARD_SCROLL_STEP", "MOUSE_WHEEL_SCROLL_STEP",
                "PC_PAUSE_KEY_HOLD_MS", "FOCUS_GAME_BEFORE_SEND",
                "PAUSE_REQUIRE_ADMIN_FOR_PC", "ADB_PAUSE_ENABLED",
                "ADB_SERIAL", "ADB_PREFER_FOR_EMULATOR",
            )
        }
        self.addCleanup(lambda: [setattr(config, name, value) for name, value in original_config.items()])
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.settings = default_settings()
        instance.settings["general"]["opacity"] = 0.7
        instance.settings["timeline"].update({
            "node_find_tolerance": 4,
            "node_click_tolerance": 5,
            "keyboard_scroll_step": 2,
            "mouse_wheel_scroll_step": 3,
        })
        instance.settings["auto_pause"]["pc_key_hold_ms"] = 80
        instance.root = MagicMock()
        instance._setup_keybindings = MagicMock()
        instance._update_display = MagicMock()

        instance._apply_global_settings()

        self.assertEqual(config.NODE_FIND_TOLERANCE, 4)
        self.assertEqual(config.NODE_CLICK_TOLERANCE, 5)
        self.assertEqual(config.KEYBOARD_SCROLL_STEP, 2)
        self.assertEqual(config.MOUSE_WHEEL_SCROLL_STEP, 3)
        self.assertEqual(config.PC_PAUSE_KEY_HOLD_MS, 80)
        instance.root.wm_attributes.assert_called_with("-alpha", 0.7)
        instance._setup_keybindings.assert_called_once()
        instance._update_display.assert_called_once()

    def test_adb_pause_accepts_configured_path_and_serial(self):
        with patch("hotkey_send._try_adb_pause_tap", return_value=(1200, 50)) as tap:
            result = hotkey_send.send_adb_pause_tap(
                serial="device-1", adb_path="custom-adb.exe", emulator_dir="C:/Emu", enabled=True
            )
        tap.assert_called_once_with(
            serial="device-1", adb_path="custom-adb.exe", emulator_dir="C:/Emu", enabled=True
        )
        self.assertEqual(result, "ADB(Tap 1200,50)")

    def test_websocket_client_keeps_configured_reconnect_delay(self):
        from websocket_client import WebsocketClient

        client = WebsocketClient("ws://127.0.0.1:2606", reconnect_delay=9)
        self.assertEqual(client.reconnect_delay, 9)

    def test_auto_detect_fills_empty_adb_but_preserves_manual_path(self):
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.settings = default_settings()
        instance._settings_path = Mock(return_value="settings.json")
        with patch("app.candidate_adb_paths", return_value=["auto.exe"]), \
             patch("app.detect_adb", return_value=AdbDetectionResult("auto.exe", ["dev"], "dev")), \
             patch("app.save_settings", side_effect=lambda _path, data: data):
            instance._auto_detect_adb_if_needed()
        self.assertEqual(instance.settings["emulator"]["adb_path"], "auto.exe")
        self.assertEqual(instance.settings["emulator"]["serial"], "dev")

        instance.settings["emulator"]["adb_path"] = "manual.exe"
        with patch("app.detect_adb") as detect:
            instance._auto_detect_adb_if_needed()
        detect.assert_not_called()
        self.assertEqual(instance.settings["emulator"]["adb_path"], "manual.exe")


if __name__ == "__main__":
    unittest.main()
