import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
from settings_manager import DEFAULT_SHORTCUTS, SettingsValidationError, validate_settings


class TestShortcutUtils(unittest.TestCase):
    def test_normalize_sequence_formats_modifiers_and_key(self):
        from shortcut_utils import normalize_sequence

        self.assertEqual(normalize_sequence("<shift-control-left>"), "<Control-Shift-Left>")
        self.assertEqual(normalize_sequence("ctrl+alt+k"), "<Control-Alt-K>")

    def test_format_key_event_ignores_modifier_only(self):
        from shortcut_utils import format_key_event

        self.assertIsNone(format_key_event(SimpleNamespace(keysym="Control_L", state=0x0004)))
        self.assertEqual(
            format_key_event(SimpleNamespace(keysym="Left", state=0x0005)),
            "<Control-Shift-Left>",
        )

    def test_display_sequence_uses_readable_key_names(self):
        from shortcut_utils import display_sequence

        self.assertEqual(display_sequence("<Control-Left>"), "Ctrl + ←")
        self.assertEqual(display_sequence("<Control-Alt-K>"), "Ctrl + Alt + K")
        self.assertEqual(display_sequence("<space>"), "Space")

    def test_defaults_cover_all_eight_actions(self):
        self.assertEqual(len(DEFAULT_SHORTCUTS), 8)
        self.assertEqual(set(DEFAULT_SHORTCUTS), {
            "move_backward", "move_forward", "previous_node", "next_node",
            "zoom_track_in", "zoom_track_out", "zoom_all_in", "zoom_all_out",
        })

    def test_normalized_duplicate_shortcuts_are_rejected(self):
        with self.assertRaises(SettingsValidationError):
            validate_settings({"shortcuts": {
                "move_backward": "ctrl+left",
                "previous_node": "<Control-Left>",
            }})

    def test_setup_keybindings_unbinds_old_and_binds_all_actions(self):
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.root = MagicMock()
        instance.settings = {"shortcuts": dict(DEFAULT_SHORTCUTS)}
        instance._bound_shortcuts = ["<F1>", "<F2>"]

        instance._setup_keybindings()

        instance.root.unbind.assert_any_call("<F1>")
        instance.root.unbind.assert_any_call("<F2>")
        bound_sequences = [call.args[0] for call in instance.root.bind.call_args_list]
        self.assertEqual(set(bound_sequences), set(DEFAULT_SHORTCUTS.values()))
        self.assertEqual(instance._bound_shortcuts, list(DEFAULT_SHORTCUTS.values()))

    def test_rebound_global_zoom_does_not_depend_on_ctrl_event_state(self):
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.root = MagicMock()
        instance.settings = {"shortcuts": {**DEFAULT_SHORTCUTS, "zoom_all_in": "<F7>"}}
        instance._bound_shortcuts = []
        instance._is_time_flowing = False
        instance._apply_global_zoom = MagicMock()
        instance._apply_track_zoom = MagicMock()

        instance._setup_keybindings()
        f7_handler = next(
            call.args[1] for call in instance.root.bind.call_args_list if call.args[0] == "<F7>"
        )
        f7_handler(SimpleNamespace(state=0))

        instance._apply_global_zoom.assert_called_once_with(0.1)
        instance._apply_track_zoom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
