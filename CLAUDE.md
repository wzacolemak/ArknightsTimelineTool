# Arknights Timeline Tool

独立打轴/对轴器。通过 WebSocket 连接最新 **Rust 费用尺**（`ws://127.0.0.1:2606`），支持多轨道编辑、提醒、到点自动暂停。

## 目录

```
timeline_tool/   # 主程序
icons/           # UI 图标
小工具/          # JSON ↔ Excel
docs/            # 设计说明
build.py         # PyInstaller 打包（仅打轴器）
```

## 运行 / 打包

```bash
pip install -r requirements.txt
cd timeline_tool && python main.py

# 打包
pip install pyinstaller
python build.py
# 输出: dist/TimelineTool_YYYYMMDD/ 与根目录 TimelineTool.exe
```

## 自动暂停

见 `timeline_tool/pause_engine.py`、`hotkey_send.py`、`game_window.py`。
