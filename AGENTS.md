# Arknights Timeline Tool：Agent 快速入口

## 项目定位

这是一个 Windows 桌面打轴器。它依赖外部 Rust 费用尺提供实时帧数，默认连接 `ws://127.0.0.1:2606`。费用尺不在本仓库内，也不由 `build.py` 打包。

本项目从 `duke4994/ArknightsCostBarRuler_-` 的 `timeline_tool` 分离而来。多轨时间轴、节点提醒、头像和费用尺模拟器支持属于上游已有能力；本 Fork 的重点是独立发布、适配新版 Rust 费用尺和自动暂停。

## 常用目录

- `timeline_tool/`：应用源码、测试、干员头像和配置。
- `timeline_tool/main.py`：开发环境入口。
- `timeline_tool/app.py`：主窗口和交互流程。
- `timeline_tool/config.py`：帧率、费用尺地址、自动暂停和 ADB 配置。
- `小工具/`：时间轴 JSON 与 Excel 互转脚本。
- `build.py`：Windows 单文件可执行程序打包脚本。
- `LICENSES/`：第三方许可证文本。

## Python 环境与命令

本机 Python 使用 uv 管理。优先使用项目根目录的 `.venv`，不要假定全局 `python` 命令存在。

```powershell
# 项目根目录
uv venv
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe timeline_tool\main.py

# 测试必须从 timeline_tool/ 运行，测试使用平铺模块导入
cd timeline_tool
..\.venv\Scripts\python.exe -m unittest discover -p "test_*.py" -v

# 从项目根目录打包
.\.venv\Scripts\python.exe build.py
```

## 工作约束

- 自动暂停会向游戏发送输入。改动窗口选择、输入或 ADB 行为前，先补覆盖错误路径的测试。
- 时间轴使用 30 个逻辑帧每秒；费用尺中的 `60f`、`120f` 表示费用回复周期，不是显示器刷新率。
- 保留现有未提交改动，避免重置、覆盖或清理无关文件。
- 修改 README 时只说明功能和使用方法；不要把上游已有功能写成 Fork 新增，也不要写实现细节。
- 改动完成后至少运行相关单测；涉及多个模块时运行完整测试集，并执行 `git diff --check`。
