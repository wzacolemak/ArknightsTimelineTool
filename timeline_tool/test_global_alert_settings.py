import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
from settings_manager import default_settings
from timeline_track import TimelineTrack


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class TestGlobalAlertSettings(unittest.TestCase):
    def test_track_dump_omits_legacy_reminder_fields(self):
        track = TimelineTrack.__new__(TimelineTrack)
        track.name = "轨道"
        track.mode = FakeVar("对轴模式")
        track.magnet_mode = FakeVar(True)
        track.pause_enabled = FakeVar(True)
        track.timeline_data = []

        dumped = track.dump_data()

        self.assertNotIn("sound_alert_enabled", dumped)
        self.assertNotIn("visual_alert_enabled", dumped)
        self.assertNotIn("alert_lead_frames", dumped)
        self.assertIn("pause_enabled", dumped)

    def test_two_tracks_read_the_same_app_reminder_settings(self):
        shared_app = Mock()
        shared_app.sound_alert_enabled = FakeVar(False)
        shared_app.visual_alert_enabled = FakeVar(True)
        shared_app.alert_lead_var = FakeVar("27")
        first = TimelineTrack.__new__(TimelineTrack)
        second = TimelineTrack.__new__(TimelineTrack)
        first.app = second.app = shared_app

        self.assertFalse(first._global_alert_value("sound_enabled"))
        self.assertTrue(second._global_alert_value("visual_enabled"))
        self.assertEqual(first._global_alert_value("alert_lead_frames"), 27)

    def test_visual_alert_uses_global_switch_and_lead(self):
        track = TimelineTrack.__new__(TimelineTrack)
        track.app = Mock(
            sound_alert_enabled=FakeVar(False),
            visual_alert_enabled=FakeVar(True),
            alert_lead_var=FakeVar("5"),
        )
        track.last_sound_alert_frame = -1
        track.is_flashing = False
        track._start_flash_loop = Mock()
        track._stop_flash_loop = Mock()

        track._handle_alerts(5, 10)
        track._start_flash_loop.assert_called_once()

        track.is_flashing = False
        track.app.visual_alert_enabled.set(False)
        track._start_flash_loop.reset_mock()
        track._handle_alerts(1, 10)
        track._start_flash_loop.assert_not_called()

    def test_app_pause_lead_reads_global_settings_variable(self):
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.pause_lead_var = FakeVar("6")
        self.assertEqual(instance._get_pause_lead_frames(), 6)

    def test_old_track_reminders_migrate_only_when_settings_were_missing(self):
        instance = app.TimelineApp.__new__(app.TimelineApp)
        instance.settings = default_settings()
        instance._settings_was_missing = True
        instance.sound_alert_enabled = FakeVar(True)
        instance.visual_alert_enabled = FakeVar(True)
        instance.alert_lead_var = FakeVar("60")
        instance._save_global_settings = Mock()
        data = {"tracks": [{
            "sound_alert_enabled": False,
            "visual_alert_enabled": False,
            "alert_lead_frames": 25,
        }]}

        instance._migrate_legacy_alerts_from_timeline(data)

        self.assertFalse(instance.sound_alert_enabled.get())
        self.assertFalse(instance.visual_alert_enabled.get())
        self.assertEqual(instance.alert_lead_var.get(), "25")
        instance._save_global_settings.assert_called_once()
        self.assertFalse(instance._settings_was_missing)


if __name__ == "__main__":
    unittest.main()
