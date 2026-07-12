import inspect
import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
from settings_manager import default_settings


class TestSettingsDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def make_dialog(self, on_save=None):
        from settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.root, default_settings(), on_save or Mock())
        self.root.update_idletasks()
        self.addCleanup(lambda: dialog.window.winfo_exists() and dialog.window.destroy())
        return dialog

    def test_has_seven_expected_tabs_and_white_background(self):
        dialog = self.make_dialog()
        self.assertEqual(dialog.tab_titles, [
            "常规", "提醒", "时间轴", "快捷键", "费用尺", "自动暂停", "模拟器",
        ])
        self.assertEqual(
            dialog.window.winfo_rgb(dialog.window.cget("background")),
            dialog.window.winfo_rgb("white"),
        )

    def test_exposes_key_controls_and_adb_actions(self):
        dialog = self.make_dialog()
        for dotted in (
            "general.opacity", "alerts.sound_enabled", "alerts.visual_enabled",
            "alerts.alert_lead_frames", "alerts.pause_lead_frames",
            "timeline.node_find_tolerance", "timeline.node_click_tolerance",
            "ruler.websocket_uri", "auto_pause.pc_key_hold_ms",
            "emulator.install_dir", "emulator.adb_path", "emulator.serial",
        ):
            self.assertIn(dotted, dialog.variables)
        self.assertIsNotNone(dialog.detect_button)
        self.assertIsNotNone(dialog.refresh_devices_button)
        self.assertIsNotNone(dialog.test_adb_button)

    def test_save_validates_and_calls_callback(self):
        callback = Mock()
        dialog = self.make_dialog(callback)
        dialog.variables["alerts.pause_lead_frames"].set("4")
        dialog._save()
        callback.assert_called_once()
        saved, restart_required = callback.call_args.args
        self.assertEqual(saved["alerts"]["pause_lead_frames"], 4)
        self.assertFalse(restart_required)

    def test_ruler_change_requests_restart(self):
        callback = Mock()
        dialog = self.make_dialog(callback)
        dialog.variables["ruler.websocket_uri"].set("ws://127.0.0.1:9999")
        dialog._save()
        self.assertTrue(callback.call_args.args[1])

    def test_restore_defaults_resets_shortcuts_and_values(self):
        dialog = self.make_dialog()
        dialog.variables["general.opacity"].set("0.4")
        dialog.variables["shortcuts.move_backward"].set("<F8>")
        dialog._restore_defaults()
        self.assertEqual(float(dialog.variables["general.opacity"].get()), 0.85)
        self.assertEqual(dialog.variables["shortcuts.move_backward"].get(), "<Left>")

    def test_shortcut_entries_are_read_only_and_show_readable_names(self):
        dialog = self.make_dialog()
        path = "shortcuts.previous_node"
        self.assertEqual(str(dialog.shortcut_entries[path].cget("state")), "readonly")
        self.assertEqual(dialog.shortcut_display_vars[path].get(), "Ctrl + ←")

    def test_clicking_shortcut_enters_capture_mode(self):
        dialog = self.make_dialog()
        path = "shortcuts.move_backward"

        dialog._begin_shortcut_capture(path)

        self.assertEqual(dialog._shortcut_capture_path, path)
        self.assertEqual(dialog.shortcut_display_vars[path].get(), "请按快捷键…")

    def test_modifier_only_waits_then_combination_is_captured(self):
        dialog = self.make_dialog()
        path = "shortcuts.move_backward"
        dialog._begin_shortcut_capture(path)

        result = dialog._handle_shortcut_key(SimpleNamespace(keysym="Control_L", state=0x0004))
        self.assertEqual(result, "break")
        self.assertEqual(dialog.variables[path].get(), "<Left>")
        self.assertEqual(dialog._shortcut_capture_path, path)

        dialog._handle_shortcut_key(SimpleNamespace(keysym="K", state=0x0005))
        self.assertEqual(dialog.variables[path].get(), "<Control-Shift-K>")
        self.assertEqual(dialog.shortcut_display_vars[path].get(), "Ctrl + Shift + K")
        self.assertIsNone(dialog._shortcut_capture_path)

    def test_escape_cancels_capture_and_restores_original_value(self):
        dialog = self.make_dialog()
        path = "shortcuts.move_backward"
        dialog._begin_shortcut_capture(path)

        dialog._handle_shortcut_key(SimpleNamespace(keysym="Escape", state=0))

        self.assertEqual(dialog.variables[path].get(), "<Left>")
        self.assertEqual(dialog.shortcut_display_vars[path].get(), "←")
        self.assertIsNone(dialog._shortcut_capture_path)

    def test_app_has_top_bar_settings_entry(self):
        source = inspect.getsource(app.TimelineApp._setup_ui)
        self.assertIn("top_settings_btn", source)
        self.assertIn("_open_settings_dialog", source)


if __name__ == "__main__":
    unittest.main()
