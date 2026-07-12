"""发布包资源选择测试。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build


class TestReleaseResources(unittest.TestCase):
    def test_copy_extra_files_excludes_portrait_assets_and_alias_sheet(self):
        """发行包不再携带未使用的头像目录和别名表。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            timeline = root / "timeline_tool"
            portraits = timeline / "operator_portraits"
            target = root / "release"
            timeline.mkdir()
            portraits.mkdir()
            target.mkdir()
            (root / "README.md").write_text("readme", encoding="utf-8")
            (timeline / "naming_config.json").write_text("{}", encoding="utf-8")
            (timeline / "operator_aliases.xlsx").write_bytes(b"unused")
            (portraits / "A41_夜刀.png").write_bytes(b"unused")

            with patch.object(build, "BASE_DIR", str(root)), patch.object(
                build, "TIMELINE_DIR", str(timeline)
            ):
                build.copy_extra_files(str(target))

            self.assertTrue((target / "README.md").is_file())
            self.assertTrue((target / "naming_config.json").is_file())
            self.assertFalse((target / "operator_aliases.xlsx").exists())
            self.assertFalse((target / "operator_portraits").exists())

    def test_locked_root_exe_does_not_abort_release_build(self):
        """根目录快捷 EXE 被运行中的程序锁定时，发行目录仍应继续打包。"""
        with patch("build.shutil.copy", side_effect=PermissionError("locked")):
            copied = build.copy_convenience_exe("release.exe", "TimelineTool.exe")

        self.assertFalse(copied)


if __name__ == "__main__":
    unittest.main()
