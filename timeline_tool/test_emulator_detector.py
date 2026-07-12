import os
import tempfile
import unittest
from pathlib import Path


class TestEmulatorDetector(unittest.TestCase):
    def _touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return str(path)

    def test_user_directory_candidates_have_highest_priority(self):
        from emulator_detector import candidate_adb_paths

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_adb = self._touch(root / "shell" / "adb.exe")
            process_adb = self._touch(root / "running" / "adb.exe")
            candidates = candidate_adb_paths(
                user_dir=root,
                process_executables=[root / "running" / "dnplayer.exe"],
                registry_dirs=[],
                common_dirs=[],
                path_adb=None,
                env={},
            )
            self.assertEqual(candidates[0], user_adb)
            self.assertIn(process_adb, candidates)

    def test_running_process_directory_derives_known_adb(self):
        from emulator_detector import candidate_adb_paths

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            process = root / "nx_device" / "12.0" / "shell" / "MuMuPlayer.exe"
            expected = self._touch(root / "nx_main" / "adb.exe")
            candidates = candidate_adb_paths(
                process_executables=[process],
                registry_dirs=[], common_dirs=[], path_adb=None, env={},
            )
            self.assertIn(expected, candidates)

    def test_registry_then_common_then_path_fallback_order(self):
        from emulator_detector import candidate_adb_paths

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_adb = self._touch(root / "registry" / "adb.exe")
            common_adb = self._touch(root / "common" / "adb.exe")
            path_adb = self._touch(root / "path" / "adb.exe")
            candidates = candidate_adb_paths(
                registry_dirs=[root / "registry"],
                common_dirs=[root / "common"],
                process_executables=[], path_adb=path_adb, env={},
            )
            self.assertLess(candidates.index(registry_adb), candidates.index(common_adb))
            self.assertLess(candidates.index(common_adb), candidates.index(path_adb))

    def test_detect_rejects_invalid_adb_and_uses_next_candidate(self):
        from emulator_detector import detect_adb

        calls = []
        def runner(args, timeout=5.0):
            calls.append(args)
            if args[0] == "bad.exe":
                return 1, "", "invalid"
            if args[-1] == "version":
                return 0, "Android Debug Bridge version 1.0.41", ""
            return 0, "List of devices attached\nemulator-5554\tdevice\n", ""

        result = detect_adb(["bad.exe", "good.exe"], runner=runner)
        self.assertEqual(result.adb_path, "good.exe")
        self.assertEqual(result.devices, ["emulator-5554"])
        self.assertEqual(result.selected_serial, "emulator-5554")

    def test_zero_and_multiple_devices_are_not_auto_selected(self):
        from emulator_detector import detect_adb

        def zero_runner(args, timeout=5.0):
            return (0, "Android Debug Bridge", "") if args[-1] == "version" else (0, "List of devices attached\n", "")
        zero = detect_adb(["adb.exe"], runner=zero_runner)
        self.assertIsNone(zero.selected_serial)

        def multi_runner(args, timeout=5.0):
            return (0, "Android Debug Bridge", "") if args[-1] == "version" else (
                0, "List of devices attached\na\tdevice\nb\tdevice\n", ""
            )
        multi = detect_adb(["adb.exe"], runner=multi_runner)
        self.assertEqual(multi.devices, ["a", "b"])
        self.assertIsNone(multi.selected_serial)

    def test_manual_adb_and_serial_are_preserved_without_redetect(self):
        from emulator_detector import detect_emulator

        result = detect_emulator(
            manual_adb_path="manual.exe",
            selected_serial="chosen",
            redetect=False,
            candidate_provider=lambda: ["auto.exe"],
            runner=lambda args, timeout=5.0: (0, "List of devices attached\nchosen\tdevice\n", ""),
        )
        self.assertEqual(result.adb_path, "manual.exe")
        self.assertEqual(result.selected_serial, "chosen")

    def test_adb_input_prioritizes_configured_path_and_emulator_directory(self):
        import adb_input

        adb_input._cached_adb = None
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configured = self._touch(root / "manual.exe")
            directory_adb = self._touch(root / "emulator" / "adb.exe")
            calls = []
            def run(args, timeout=5.0):
                calls.append(args[0])
                return (1, "", "bad") if args[0] == configured else (0, "Android Debug Bridge", "")

            original = adb_input._run
            adb_input._run = run
            try:
                found = adb_input.find_adb(configured_adb_path=configured, emulator_dir=root / "emulator")
            finally:
                adb_input._run = original
                adb_input._cached_adb = None
            self.assertEqual(found, directory_adb)
            self.assertEqual(calls[:2], [configured, directory_adb])


if __name__ == "__main__":
    unittest.main()
