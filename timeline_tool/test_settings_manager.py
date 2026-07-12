import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestSettingsManager(unittest.TestCase):
    def setUp(self):
        from settings_manager import default_settings

        self.defaults = default_settings()

    def test_defaults_are_nested_and_independent(self):
        from settings_manager import default_settings

        first = default_settings()
        second = default_settings()
        self.assertEqual(first["alerts"]["pause_lead_frames"], 1)
        self.assertEqual(first["timeline"]["node_find_tolerance"], 3)
        self.assertEqual(first["shortcuts"]["previous_node"], "<Control-Left>")
        first["alerts"]["pause_lead_frames"] = 9
        self.assertEqual(second["alerts"]["pause_lead_frames"], 1)

    def test_validation_merges_defaults_and_converts_numbers(self):
        from settings_manager import validate_settings

        result = validate_settings({"general": {"opacity": "0.75"}})
        self.assertEqual(result["general"]["opacity"], 0.75)
        self.assertEqual(result["alerts"], self.defaults["alerts"])

    def test_validation_rejects_out_of_range_and_wrong_boolean(self):
        from settings_manager import SettingsValidationError, validate_settings

        with self.assertRaises(SettingsValidationError):
            validate_settings({"alerts": {"pause_lead_frames": 31}})
        with self.assertRaises(SettingsValidationError):
            validate_settings({"alerts": {"sound_enabled": "yes"}})

    def test_damaged_json_falls_back_to_defaults(self):
        from settings_manager import load_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_settings(path), self.defaults)

    def test_save_is_atomic_and_leaves_no_temporary_file(self):
        from settings_manager import save_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            with mock.patch("settings_manager.os.replace", wraps=__import__("os").replace) as replace:
                save_settings(path, self.defaults)
            replace.assert_called_once()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.defaults)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_migrates_pause_and_first_track_reminders_once(self):
        from settings_manager import migrate_legacy_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            pause_path = root / "pause_settings.json"
            timeline_path = root / "timeline.json"
            pause_path.write_text('{"pause_lead_frames": 5}', encoding="utf-8")
            timeline_path.write_text(json.dumps({
                "tracks": [
                    {"sound_alert_enabled": False, "visual_alert_enabled": True, "alert_lead_frames": 42},
                    {"sound_alert_enabled": True, "visual_alert_enabled": False, "alert_lead_frames": 99},
                ]
            }), encoding="utf-8")

            migrated = migrate_legacy_settings(settings_path, pause_path, timeline_path)
            self.assertEqual(migrated["alerts"], {
                "sound_enabled": False,
                "visual_enabled": True,
                "alert_lead_frames": 42,
                "pause_lead_frames": 5,
            })

            existing = dict(migrated)
            existing["general"] = {"opacity": 0.5}
            settings_path.write_text(json.dumps(existing), encoding="utf-8")
            pause_path.write_text('{"pause_lead_frames": 8}', encoding="utf-8")
            self.assertEqual(
                migrate_legacy_settings(settings_path, pause_path, timeline_path)["general"]["opacity"],
                0.5,
            )

    def test_legacy_migration_can_be_deferred_without_creating_settings_file(self):
        from settings_manager import migrate_legacy_settings

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            pause_path = root / "pause_settings.json"
            pause_path.write_text('{"pause_lead_frames": 3}', encoding="utf-8")

            migrated = migrate_legacy_settings(settings_path, pause_path, persist=False)

            self.assertEqual(migrated["alerts"]["pause_lead_frames"], 3)
            self.assertFalse(settings_path.exists())

    def test_dotted_get_and_set(self):
        from settings_manager import get_setting, set_setting

        data = self.defaults
        set_setting(data, "alerts.pause_lead_frames", 7)
        self.assertEqual(get_setting(data, "alerts.pause_lead_frames"), 7)
        self.assertEqual(get_setting(data, "missing.value", "fallback"), "fallback")

    def test_shortcut_conflicts_are_rejected_after_normalization(self):
        from settings_manager import SettingsValidationError, validate_settings

        with self.assertRaises(SettingsValidationError):
            validate_settings({"shortcuts": {
                "move_backward": "<Control-Left>",
                "previous_node": "<control-left>",
            }})


if __name__ == "__main__":
    unittest.main()
