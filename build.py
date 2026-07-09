"""仅打包独立打轴器 TimelineTool（不再打包费用尺）。"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")
TIMELINE_DIR = os.path.join(BASE_DIR, "timeline_tool")

DATE_STR = datetime.now().strftime("%Y%m%d")
TIMELINE_NAME = f"TimelineTool_{DATE_STR}"


def clean_build():
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            print(f"清理目录: {d}")
            shutil.rmtree(d)
    os.makedirs(DIST_DIR, exist_ok=True)


def build_timeline_exe(name: str, debug: bool = False) -> None:
    main_py = os.path.join(TIMELINE_DIR, "main.py")
    icon_path = os.path.join(BASE_DIR, "icons", "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = None

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        name,
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
        "--specpath",
        BASE_DIR,
        "--clean",
        "--noconsole" if not debug else "--console",
    ]
    if icon_path:
        cmd.extend(["--icon", icon_path])

    icons_src = os.path.join(BASE_DIR, "icons")
    if os.path.exists(icons_src):
        cmd.extend(["--add-data", f"{icons_src}{os.pathsep}icons"])

    naming_src = os.path.join(TIMELINE_DIR, "naming_config.json")
    if os.path.exists(naming_src):
        cmd.extend(["--add-data", f"{naming_src}{os.pathsep}timeline_tool"])

    cmd.append(main_py)

    print(f"\n{'=' * 60}")
    print(f"正在打包: {name} ({'debug' if debug else 'release'})")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, cwd=TIMELINE_DIR)
    if result.returncode != 0:
        print(f"[错误] 打包 {name} 失败！")
        sys.exit(1)
    print(f"[成功] {name} 打包完成。")


def build_tools(target_dir: str) -> None:
    tools_src = os.path.join(BASE_DIR, "小工具")
    if not os.path.exists(tools_src):
        return
    tools_dst = os.path.join(target_dir, "小工具")
    os.makedirs(tools_dst, exist_ok=True)
    for py_file in os.listdir(tools_src):
        if not py_file.endswith(".py"):
            continue
        py_path = os.path.join(tools_src, py_file)
        name = os.path.splitext(py_file)[0]
        spec_dir = os.path.join(BUILD_DIR, "tool_specs")
        os.makedirs(spec_dir, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--noconsole",
            "--name",
            name,
            "--distpath",
            tools_dst,
            "--workpath",
            BUILD_DIR,
            "--specpath",
            spec_dir,
            "--clean",
            py_path,
        ]
        print(f"打包小工具: {name}")
        if subprocess.run(cmd).returncode != 0:
            print(f"[警告] 小工具 {name} 打包失败，跳过")


def copy_extra_files(target_dir: str) -> None:
    files_copied = []

    readme_src = os.path.join(BASE_DIR, "README.md")
    if os.path.exists(readme_src):
        shutil.copy(readme_src, os.path.join(target_dir, "README.md"))
        files_copied.append("README.md")

    for fname in ("operator_aliases.xlsx", "naming_config.json"):
        src = os.path.join(TIMELINE_DIR, fname)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(target_dir, fname))
            files_copied.append(fname)

    portraits_src = os.path.join(TIMELINE_DIR, "operator_portraits")
    if os.path.exists(portraits_src):
        portraits_dst = os.path.join(target_dir, "operator_portraits")
        if os.path.exists(portraits_dst):
            shutil.rmtree(portraits_dst)
        shutil.copytree(portraits_src, portraits_dst)
        files_copied.append("operator_portraits/")

    print(f"  已复制外部资源: {', '.join(files_copied) if files_copied else '(无)'}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    clean_build()
    folder = f"TimelineTool_{DATE_STR}"
    version_dir = os.path.join(DIST_DIR, folder)
    os.makedirs(version_dir, exist_ok=True)

    build_timeline_exe(TIMELINE_NAME, debug=False)
    src_exe = os.path.join(DIST_DIR, f"{TIMELINE_NAME}.exe")
    dst_exe = os.path.join(version_dir, f"{TIMELINE_NAME}.exe")
    if os.path.exists(src_exe):
        shutil.move(src_exe, dst_exe)
        # 根目录也放一份固定名，方便双击
        shutil.copy(dst_exe, os.path.join(BASE_DIR, "TimelineTool.exe"))
        print(f"  已输出: {dst_exe}")
        print(f"  已复制: {os.path.join(BASE_DIR, 'TimelineTool.exe')}")

    build_tools(version_dir)
    copy_extra_files(version_dir)

    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    for f in os.listdir(BASE_DIR):
        if f.endswith(".spec"):
            os.remove(os.path.join(BASE_DIR, f))

    print(f"\n完成。发布目录: {version_dir}")


if __name__ == "__main__":
    main()
