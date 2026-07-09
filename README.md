# Arknights Timeline Tool（独立打轴器）

基于 [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-) 的 `timeline_tool`，适配最新 **Rust 费用尺** WebSocket API，并增加 **到点自动暂停**。

仓库：https://github.com/wzacolemak/ArknightsTimelineTool

## 依赖

- Python 3.8+
- 费用尺运行中（默认 `ws://127.0.0.1:2606`）

```bash
pip install -r requirements.txt
```

## 运行

```bash
cd timeline_tool
python main.py
```

## 打包 exe

```bash
python build.py
```

输出：

- `dist/TimelineTool_YYYYMMDD/TimelineTool_YYYYMMDD.exe` + 干员头像等外部资源
- 项目根目录 `TimelineTool.exe`（副本）

## 自动暂停

- **对轴模式**下，帧跨过节点时向游戏窗口发送 **Space**（`config.PAUSE_HOTKEY`）
- 找窗：左侧 **「绑定游戏窗」**（3 秒内把鼠标移到目标窗）优先；否则按标题关键字匹配
- 字段 `pause_on_arrive` / `pause_enabled` 默认 true

## 测试

```bash
cd timeline_tool
python -m unittest test_pause_engine -v
```
