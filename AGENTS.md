# Arknights Timeline Tool：Agent 开发指南

## 项目定位

这是一个 Windows 桌面打轴器，配合外部 Rust 费用尺读取实时帧数，默认连接 `ws://127.0.0.1:2606`。费用尺不属于本仓库，也不会由 `build.py` 打包。

项目从 `duke4994/ArknightsCostBarRuler_-` 的 `timeline_tool` 分离而来。多轨时间轴、节点提醒和费用尺模拟器支持来自上游；本 Fork 主要维护独立发布、新版 Rust 费用尺连接和自动暂停。

## 主要模块

- `timeline_tool/main.py`：开发环境入口。
- `timeline_tool/app.py`：主窗口、轨道管理、全局设置和自动暂停流程。
- `timeline_tool/timeline_track.py`：轨道渲染、节点编辑、提醒和时间轴交互。
- `timeline_tool/pause_engine.py`、`pause_queue.py`：暂停事件计算、去重和排队。
- `timeline_tool/hotkey_send.py`：PC 客户端 ESC 输入和模拟器 ADB 暂停入口。
- `timeline_tool/adb_input.py`、`emulator_detector.py`：ADB 点击、设备选择和模拟器探测。
- `timeline_tool/settings_manager.py`、`settings_dialog.py`：全局设置的校验、迁移、保存和界面。
- `timeline_tool/websocket_client.py`：费用尺 WebSocket 客户端。
- `小工具/`：时间轴 JSON 与 Excel 互转工具。
- `build.py`：Windows 单文件 EXE 打包脚本。

## 开发环境

项目使用 uv 管理 Python 环境。在仓库根目录执行：

```powershell
uv venv
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe timeline_tool\main.py
```

测试使用平铺模块导入，必须从 `timeline_tool/` 目录运行：

```powershell
cd timeline_tool
..\.venv\Scripts\python.exe -m unittest discover -p "test_*.py" -v
```

打包从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe build.py
```

## 实现约束

- 时间轴按每秒 30 个逻辑帧工作。费用尺中的 `60f`、`120f` 是费用回复周期，不是显示器刷新率。
- 自动暂停会向游戏发送输入。修改窗口选择、PC 输入或 ADB 行为时，先为失败路径和禁止回退场景补测试。
- 模拟器暂停只能通过 ADB 点击游戏内暂停按钮，不能回退为向模拟器窗口发送 PC 按键。
- 多台 ADB 设备在线时必须由用户选择，不能默认使用第一台。
- 时间轴文件需要兼容旧字段；新增文件不应重新写入已经迁移为全局设置的轨道字段。
- 费用尺地址和重连间隔修改后重启生效，其余用户设置应尽量立即生效。

## 编写规范

- 保留现有未提交改动，不要重置、覆盖或清理无关文件。
- 新功能和缺陷修复使用测试驱动：先写能复现需求或问题的失败测试，再实现最小修改。
- 优先扩展职责明确的小模块，避免继续扩大 `app.py` 中与主窗口无关的逻辑。
- Windows 路径使用 `pathlib.Path` 或 `os.path` 处理，不在代码和文档中写入个人电脑的绝对路径。
- README 面向普通用户，只写功能、使用方法和必要限制；不要把上游已有功能描述为本 Fork 新增，也不要写内部实现过程。
- 不提交运行时配置、时间轴数据、构建目录、EXE、日志或本机 Agent 偏好。

## 测试与提交

- 单模块修改至少运行对应测试；跨模块修改运行完整测试集。
- 提交前执行 `git diff --check`。涉及打包资源或入口时，再运行 `build.py`。
- 提交保持单一目的，不混入格式化、资源清理或其它无关改动。
- 提交信息采用 Conventional Commits，例如：
  - `feat: add shortcut key capture`
  - `fix: require explicit adb device selection`
  - `docs: update agent development guide`
  - `test: cover locked executable build`
- Pull Request 说明应包含功能变化、兼容性影响和实际执行过的测试命令。
