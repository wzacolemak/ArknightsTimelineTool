# Arknights Timeline Tool

配合明日方舟费用尺使用的独立打轴器，可记录操作节点、对照时间轴，并按节点自动暂停游戏。

本项目从 [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-) 的 `timeline_tool` 分离而来。多轨时间轴、节点提醒和费用尺模拟器支持来自上游；本 Fork 增加了独立发布、新版 Rust 费用尺连接和自动暂停。

## 下载与启动

1. 前往 [Releases](../../releases) 下载 Windows 压缩包并完整解压。
2. 启动新版 Rust 费用尺。费用尺不包含在本项目中，默认地址为 `ws://127.0.0.1:2606`。
3. 运行 `TimelineTool_YYYYMMDD.exe`。

如果时间轴没有跟随帧数，请检查费用尺是否启动，并确认没有同时运行多个费用尺实例。

## 基本使用

每条轨道可以单独选择「打轴模式」或「对轴模式」。

- 打轴模式：移动蓝色中心线，在需要记录的位置添加节点并填写名称。
- 对轴模式：轨道跟随费用尺，接近节点时显示预告并发出提醒。
- 磁铁开启时轨道跟随费用尺；关闭后可以自由查看其它位置。

常用操作：

- `←`、`→` 或鼠标滚轮：移动 1 帧。
- `Ctrl+←`、`Ctrl+→`：跳转到前一个、后一个节点。
- `↑`、`↓`：缩放当前轨道。
- `Ctrl+↑`、`Ctrl+↓`：缩放全部轨道。

单击节点前后 3 帧会吸附到该节点，中心线在节点前后 3 帧内时可以选中并编辑。吸附范围、选中范围和移动步数都能在设置中修改。

## 设置

点击顶栏「设置」可以调整透明度、提醒、时间轴操作、快捷键、费用尺、自动暂停和模拟器连接。

声音提醒、视觉提醒、提醒提前帧数和暂停提前帧数是全局设置，对所有轨道生效。快捷键点击后直接按键录入，重复的快捷键无法保存。

费用尺地址和重连间隔在重启后生效，其余设置保存后立即生效。

## 自动暂停

打轴和对轴模式都可以启用自动暂停：

1. 打开轨道的「轨暂停」。
2. 选中暂停节点，在节点配置中打开「到点自动暂停」。
3. 点击「绑定游戏窗」，将鼠标移到游戏窗口。
4. 在「设置 → 提醒」中调整暂停提前帧数。

轨道开关和节点开关需要同时开启。暂停提前默认是 1 帧。

发送输入、游戏响应和费用尺读取都有延迟，实际停帧可能存在误差。相距 5 帧以内的连续暂停点容易漏掉后一个节点。

> **请根据电脑延迟留出足够的提前量，并配合 AFA 或「划火柴」等工具精确过帧。不要把自动暂停节点设置得太近。**

推荐使用两条轨道：一条只放自动暂停节点，另一条记录完整操作和提醒节点。

PC 客户端启用自动暂停时，需要以管理员身份运行打轴器。

MuMu、雷电等模拟器不需要管理员权限，但需要开启 ADB。模拟器分辨率需为不低于 `1280×720` 的 `16:9`；ADB 可以自动探测，也可以在「设置 → 模拟器」中指定模拟器目录或 `adb.exe`。检测到多台设备时需要手动选择。

## 保存与导入

顶栏的打开和保存按钮用于读写整份时间轴 JSON 文件。

`小工具/` 提供两项转换工具：

- `json_to_excel.py`：把时间轴转成 Excel。
- `excel_to_json.py`：把 Excel 转回时间轴。

## 编译与开发

项目使用 uv 管理 Python 环境：

```powershell
uv venv
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe timeline_tool\main.py
```

运行测试：

```powershell
cd timeline_tool
..\.venv\Scripts\python.exe -m unittest discover -p "test_*.py" -v
```

生成 Windows EXE：

```powershell
.\.venv\Scripts\python.exe build.py
```

费用尺需要单独启动，不会被打包进 EXE。

## 更新日志

### v0.0.1（测试版，2026-07-13）

- 首个测试版本，支持多轨打轴、对轴、节点提醒和自动暂停。
- 提供统一设置窗口，可调整提醒、暂停提前量、时间轴操作和快捷键。
- 支持模拟器与 ADB 探测、设备选择和连接测试。
- 快捷键可直接按键录入。
- 提供独立 Windows 发行包。

## 开源协议与鸣谢

本项目使用 [MIT License](LICENSE)，第三方许可证见 `LICENSES/`。欢迎提交 Issue 和 Pull Request。

感谢以下项目：

- [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-)
- [ZeroAd-06/ArknightsCostBarRuler](https://github.com/ZeroAd-06/ArknightsCostBarRuler)
- [MaaFramework](https://github.com/MaaXYZ/MaaFramework)
- [Minicap](https://github.com/DeviceFarmer/minicap)
- [Google Material Symbols](https://fonts.google.com/icons)
