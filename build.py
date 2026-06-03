import os
import shutil
import subprocess
import sys
from datetime import datetime

# === 基础路径配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")

RULER_DIR = os.path.join(BASE_DIR, "ruler")
TIMELINE_DIR = os.path.join(BASE_DIR, "timeline_tool")

# === 版本与命名（自动使用当前日期）===
DATE_STR = datetime.now().strftime("%Y%m%d")

RULER_NAME = f"ArknightsCostBarRuler_{DATE_STR}"
TIMELINE_NAME = f"TimelineTool_{DATE_STR}"
RULER_DEBUG_NAME = f"ArknightsCostBarRuler_Debug_{DATE_STR}"
TIMELINE_DEBUG_NAME = f"TimelineTool_Debug_{DATE_STR}"


def clean_build():
    """清理旧的构建输出。"""
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            print(f"清理目录: {d}")
            shutil.rmtree(d)
    os.makedirs(DIST_DIR, exist_ok=True)


def build_exe(source_dir, name, debug=False, uac_admin=False):
    """
    使用 PyInstaller 打包单个 exe。

    Args:
        source_dir: 源码目录（如 ruler/ 或 timeline_tool/）
        name: 输出的 exe 名称（不含 .exe）
        debug: 是否为 debug 版本（显示控制台）
        uac_admin: 是否在 manifest 中嵌入 requireAdministrator（双击自动请求管理员权限）
    """
    main_py = os.path.join(source_dir, "main.py")
    icon_path = os.path.join(source_dir, "icons", "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", name,
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--specpath", BASE_DIR,
        "--clean",
    ]

    if not debug:
        cmd.append("--noconsole")
    else:
        cmd.append("--console")

    if uac_admin:
        cmd.append("--uac-admin")

    if icon_path:
        cmd.extend(["--icon", icon_path])

    # === 添加内部资源（打包进 exe）===

    # 图标资源（ruler 和 timeline_tool 共用项目根目录的 icons/）
    icons_src = os.path.join(BASE_DIR, "icons")
    if os.path.exists(icons_src):
        cmd.extend(["--add-data", f"{icons_src}{os.pathsep}icons"])

    # timeline_tool 特有的内部资源
    if "timeline" in source_dir.lower():
        naming_src = os.path.join(source_dir, "naming_config.json")
        if os.path.exists(naming_src):
            # 必须打包到 timeline_tool/ 子目录下，与 naming_manager.py 中的 resource_path 期望一致
            cmd.extend(["--add-data", f"{naming_src}{os.pathsep}timeline_tool"])

    cmd.append(main_py)

    print(f"\n{'='*60}")
    print(f"正在打包: {name}")
    print(f"模式: {'Debug（带控制台）' if debug else 'Release（无控制台）'}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=source_dir)
    if result.returncode != 0:
        print(f"[错误] 打包 {name} 失败！")
        sys.exit(1)
    print(f"[成功] {name} 打包完成。")


def copy_extra_files(target_dir):
    """
    复制外部资源文件到输出目录（exe 同级）。
    这些文件不会被打包进 exe 内部，方便用户查看和修改。
    """
    files_copied = []

    # README
    readme_src = os.path.join(BASE_DIR, "README.md")
    if os.path.exists(readme_src):
        shutil.copy(readme_src, os.path.join(target_dir, "README.md"))
        files_copied.append("README.md")

    # 配置模板（仅作为参考，不会自动成为 config.json）
    # 首次运行时不存在 config.json，费用尺会自动弹出设置向导
    config_template_src = os.path.join(BASE_DIR, "config_template.json")
    if os.path.exists(config_template_src):
        shutil.copy(config_template_src, os.path.join(target_dir, "config_template.json"))
        files_copied.append("config_template.json")

    # 校准目录（外部数据，用户可自由添加/修改校准文件）
    calib_src = os.path.join(BASE_DIR, "calibration")
    if os.path.exists(calib_src):
        calib_dst = os.path.join(target_dir, "calibration")
        if os.path.exists(calib_dst):
            shutil.rmtree(calib_dst)
        shutil.copytree(calib_src, calib_dst)
        files_copied.append("calibration/")

    # 干员昵称映射表
    alias_src = os.path.join(TIMELINE_DIR, "operator_aliases.xlsx")
    if os.path.exists(alias_src):
        shutil.copy(alias_src, os.path.join(target_dir, "operator_aliases.xlsx"))
        files_copied.append("operator_aliases.xlsx")

    # 保存时命名配置文件（用户可自定义字段和开关）
    naming_src = os.path.join(TIMELINE_DIR, "naming_config.json")
    if os.path.exists(naming_src):
        shutil.copy(naming_src, os.path.join(target_dir, "naming_config.json"))
        files_copied.append("naming_config.json")

    # 干员头像目录
    portraits_src = os.path.join(TIMELINE_DIR, "operator_portraits")
    if os.path.exists(portraits_src):
        portraits_dst = os.path.join(target_dir, "operator_portraits")
        if os.path.exists(portraits_dst):
            shutil.rmtree(portraits_dst)
        shutil.copytree(portraits_src, portraits_dst)
        files_copied.append("operator_portraits/")

    if files_copied:
        print(f"  已复制外部资源: {', '.join(files_copied)}")
    else:
        print("  警告: 未找到任何外部资源可复制。")


def package_version(folder_name, ruler_name, timeline_name, debug=False):
    """打包一个完整版本（正常版或 debug 版）。"""
    version_dir = os.path.join(DIST_DIR, folder_name)
    os.makedirs(version_dir, exist_ok=True)
    print(f"\n{'#'*60}")
    print(f"# 开始构建: {folder_name}")
    print(f"{'#'*60}")

    # 打包费用尺（费用尺需要管理员权限以调用 dnconsole.exe 等模拟器工具）
    build_exe(RULER_DIR, ruler_name, debug=debug, uac_admin=True)
    # 打包打轴器（打轴器不需要管理员权限）
    build_exe(TIMELINE_DIR, timeline_name, debug=debug)

    # 移动 exe 到版本目录
    for name in [f"{ruler_name}.exe", f"{timeline_name}.exe"]:
        src = os.path.join(DIST_DIR, name)
        dst = os.path.join(version_dir, name)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  移动: {name} -> {folder_name}/")
        else:
            print(f"  警告: 未找到 {name}")

    # 复制外部资源
    print(f"\n复制外部资源到 {folder_name}/ ...")
    copy_extra_files(version_dir)


def main():
    # 避免 Windows GBK 终端在打印含生僻字文件名时崩溃
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    clean_build()

    # === 正常版 ===
    package_version(
        f"费用尺+打轴器_{DATE_STR}",
        RULER_NAME,
        TIMELINE_NAME,
        debug=False
    )

    # === Debug 版 ===
    package_version(
        f"费用尺+打轴器_{DATE_STR}_debug版",
        RULER_DEBUG_NAME,
        TIMELINE_DEBUG_NAME,
        debug=True
    )

    # === 清理 ===
    # 清理 PyInstaller 工作目录
    if os.path.exists(BUILD_DIR):
        print(f"\n清理工作目录: {BUILD_DIR}")
        shutil.rmtree(BUILD_DIR)

    # 清理遗留的 .spec 文件
    spec_files = [
        os.path.join(BASE_DIR, f"{RULER_NAME}.spec"),
        os.path.join(BASE_DIR, f"{TIMELINE_NAME}.spec"),
        os.path.join(BASE_DIR, f"{RULER_DEBUG_NAME}.spec"),
        os.path.join(BASE_DIR, f"{TIMELINE_DEBUG_NAME}.spec"),
    ]
    for spec in spec_files:
        if os.path.exists(spec):
            os.remove(spec)
            print(f"清理 .spec 文件: {os.path.basename(spec)}")

    # === 完成报告 ===
    print(f"\n{'='*60}")
    print("所有打包任务已完成！")
    print(f"输出目录: {DIST_DIR}")
    print(f"{'='*60}")
    print("\n目录结构:")
    for root, dirs, files in os.walk(DIST_DIR):
        level = root.replace(DIST_DIR, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        sub_indent = ' ' * 2 * (level + 1)
        for file in files:
            print(f"{sub_indent}{file}")


if __name__ == "__main__":
    main()
