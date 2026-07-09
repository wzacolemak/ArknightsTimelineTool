# 独立打轴器（TimelineTool）设计

日期：2026-07-10  
状态：已确认（用户同意独立程序 + 自动暂停 + 标题匹配/点选绑定）

## 1. 目标

在 **duke4994/ArknightsCostBarRuler_- 的 `timeline_tool/`** 基础上，做**独立打轴器**，连接**最新 Rust 费用尺** API，并增加**到点自动暂停**。

不把打轴 UI 嵌进 ruler-app。

## 2. 仓库与依赖

| 组件 | 位置 |
|---|---|
| 打轴器 | 本目录 `E:\game\ArknightsTimelineTool`（源码来自 duke `timeline_tool` + `icons`） |
| 费用尺 | 独立进程；干净分支 `rust-rewrite` / v2.3.2 |
| 时间源 | `ws://127.0.0.1:2606` 顶层推送：`isRunning`、`totalElapsedFrames` |

尺子 API **不**暴露游戏 hwnd/进程；自动暂停由打轴器本机找窗 + SendInput。

## 3. 架构

```
[Rust 费用尺 :2606] --WS 快照--> [TimelineTool]
                                    |-- UI（原 tk/ttkbootstrap，基本不动）
                                    |-- pause_engine：帧边沿 + 去重
                                    |-- game_window：标题匹配 + 点选绑定
                                    |-- hotkey_send：SendInput(Space) + 可选置前
```

## 4. 自动暂停

### 触发条件（全部满足）

1. 轨道 `mode == "对轴模式"`
2. 轨道 `pause_enabled`（默认 true）
3. 节点 `pause_on_arrive`（默认 true）
4. 边沿：`last_frame < node.frame <= current_frame`
5. 本局未对该 `(track_idx, frame)` 发过键

### 重置

`totalElapsedFrames` 相对上次回退超过阈值（如 30 帧）→ 清空去重表。

### 发键

- 默认键：`Space`（可配置）
- 方式：Windows `ctypes` + `SendInput`
- 默认 `focus_game_before_send=true`（`SetForegroundWindow` 后发键）
- 失败只打日志，不抛到 UI

### 找窗

1. **点选绑定**优先：用户点「绑定游戏窗」→ 倒计时内点击目标 → 记住 title/class
2. **标题关键字**回退：配置列表（MuMu、雷电、明日方舟…）枚举顶层窗
3. 找不到：跳过发键 + 状态提示

## 5. 数据格式增量

JSON 轨道/节点可选字段（缺省 true，旧文件兼容）：

```json
{
  "tracks": [{
    "name": "轨道0",
    "mode": "对轴模式",
    "pause_enabled": true,
    "nodes": [{"frame": 90, "name": "A", "color": "#5ac8d8", "pause_on_arrive": true}]
  }]
}
```

`file_io._normalize_track_data` / 节点规范化补默认值。

## 6. 配置（`pause_config.json` 或并入本地配置）

- `websocket_uri`
- `pause_hotkey`（默认 `"Space"`）
- `focus_game_before_send`
- `window_title_keywords: string[]`
- `bound_window`: `{title, class_name}` 可选

## 7. 非目标

- 不改 Rust 尺子核心
- 不在尺子 API 加 hwnd（除非另开需求）
- 本阶段可不做 PyInstaller（开发用 `python main.py`）

## 8. 验收

1. 尺子运行 + 打轴器连接，帧与原 UI 正常  
2. 对轴跨节点 → 游戏暂停  
3. 自动匹配与点选绑定均可用  
4. 旧 JSON 可打开；无暂停字段时默认允许暂停  

## 9. 与旧内嵌方案关系

`feature/timeline-tool`（Rust 内嵌）废弃；日常尺子用 `rust-rewrite`。  
GitHub 上旧尺子 fork 删除需 `delete_repo` 权限，用户可自行删；本地克隆保留。
