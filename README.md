# Arknights Timeline Tool

一个配合明日方舟费用尺使用的独立打轴器。它会读取费用尺的实时帧数，帮助记录操作节点、对照时间轴，并在需要时自动暂停游戏。

本项目从 [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-) 的 `timeline_tool` 分离而来。原项目已经提供多轨时间轴、节点提醒、干员头像和费用尺模拟器支持，改动如下

- 独立发布打轴器，不再打包原费用尺。
- 对接新版 Rust 费用尺。
- 在对轴流程中加入自动暂停。

## 下载与启动

1. 前往 [Releases](../../releases) 下载 `TimelineTool_vX.Y.Z_windows_x64.zip`。
2. 解压整个压缩包，不要只取出其中的 EXE。头像、别名表等文件需要和程序放在同一目录。
3. 启动新版 Rust 费用尺。本项目不附带费用尺，默认连接 `ws://127.0.0.1:2606`。
4. 双击 `TimelineTool_YYYYMMDD.exe` 启动打轴器。

打轴器会自动连接费用尺。没有跟随帧数时，检查费用尺是否已启动，并确认本机只运行了一个费用尺实例。

## 打轴与对轴

每条轨道都可以单独切换为「打轴模式」或「对轴模式」。

- 打轴时，把蓝色中心线移到需要记录的帧，添加节点，再填写名称和颜色。
- 对轴时，轨道会跟随费用尺当前帧。节点接近时可以显示预告、播放提示音或进行视觉提醒。
- 一个文件可以保存多条轨道，适合记录不同编队、不同思路，或把多个操作阶段放在一起对照。

节点名称支持干员头像标记。例如输入 `[A41]开局部署`，会显示夜刀头像和后面的文字。干员别名可在 `timeline_tool/operator_aliases.xlsx` 中维护。

### 时间轴操作

- 开启磁铁时，蓝色中心线跟随费用尺；关闭后可以自由查看其它位置。
- `←`、`→` 每次移动 1 帧，方便微调。
- 鼠标停在轨道上滚动滚轮，每格移动 10 帧。
- 费用尺正在计时时，对轴轨道会保持跟随，避免误拖离当前时间。
- 顶栏可以新建、删除和切换轨道；在顶栏空白处拖动可移动窗口。底部和右侧把手分别调整高度、宽度。

## 自动暂停

自动暂停只在「对轴模式」下生效。

1. 在左侧操作面板打开轨道的「轨暂停」。
2. 在节点配置中确认「到点自动暂停」已开启。
3. 点击「绑定游戏窗」，在倒计时结束前把鼠标移到目标游戏窗口。
4. 设置「暂停提前（帧）」后开始对轴。到达节点前，打轴器会按设置提前暂停。

同一帧的多个节点只暂停一次；不同帧的节点会在每次恢复游戏后依次暂停。

PC 客户端建议以管理员身份运行 TimelineTool，否则系统可能拦截自动暂停。模拟器会优先使用 ADB 输入；多开模拟器时，请在 `timeline_tool/config.py` 中填写正确的 `ADB_SERIAL`。

## 保存与导入

顶栏右侧提供打开和保存按钮，用于读写整份时间轴 JSON 文件。

`小工具/` 目录提供 JSON 与 Excel 的互转工具，适合批量修改节点名称和帧数：

- `json_to_excel.py`：把时间轴 JSON 转成 Excel。
- `excel_to_json.py`：把编辑后的 Excel 转回时间轴 JSON。

## 开源协议与鸣谢

本项目以 [MIT License](LICENSE) 开源，保留上游和第三方依赖的许可证文件，详见 `LICENSES/`。

感谢以下项目和贡献者：

- [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-)：本项目的直接上游。
- [ZeroAd-06/ArknightsCostBarRuler](https://github.com/ZeroAd-06/ArknightsCostBarRuler)：上游项目的基础版本。
- [MaaFramework](https://github.com/MaaXYZ/MaaFramework)：窗口识别策略的参考来源。
- [Minicap](https://github.com/DeviceFarmer/minicap) 与 [Google Material Symbols](https://fonts.google.com/icons)：上游保留的资源和许可证说明。

欢迎提交 Issue、PR 和使用反馈。提交代码前请运行完整测试，并说明改动影响的功能范围。
