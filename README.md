# Arknights Timeline Tool（独立打轴器）

基于 [duke4994/ArknightsCostBarRuler_-](https://github.com/duke4994/ArknightsCostBarRuler_-) 的 `timeline_tool`，适配最新 **Rust 费用尺** WebSocket API，并增加 **到点自动暂停**。

## 依赖

- Python 3.8+
- 费用尺运行中（默认 `ws://127.0.0.1:2606`）

```text
pip install ttkbootstrap pillow websockets
```

（Windows 自带 `winsound` / `ctypes`）

## 运行

```text
cd timeline_tool
python main.py
```

先启动费用尺（干净分支 `rust-rewrite` / 发行版均可），再启动本程序。

## 自动暂停

- **对轴模式**下，帧跨过节点时向游戏窗口发送 **Space**（可改 `config.PAUSE_HOTKEY`）
- 找窗：左侧 **「绑定游戏窗」**（3 秒内把鼠标移到目标窗）优先；否则按 `GAME_WINDOW_TITLE_KEYWORDS` 匹配标题
- 节点/轨道字段 `pause_on_arrive` / `pause_enabled` 默认 true，旧 JSON 兼容

## 目录

见 `docs/2026-07-10-timeline-tool-standalone-design.md`。

## 测试（无需游戏）

```text
cd timeline_tool
python -m unittest test_pause_engine -v
```
