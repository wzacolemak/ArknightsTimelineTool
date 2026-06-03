import tkinter as tk
import ttkbootstrap as ttkb
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import TimelineApp
import config

def run_all_tests():
    """在一个 root 内完成所有测试，避免 ttkbootstrap 多次初始化问题。"""
    root = ttkb.Window(themename="darkly")
    root.withdraw()
    app = TimelineApp(root, scaling_factor=1.0)

    print("=" * 60)
    print("测试1: 轨道高度自动调整")
    print("=" * 60)
    base_height = app.scaled_win_height
    print(f"初始高度（1条轨道）: {base_height}")
    assert base_height >= app._get_minimum_height(), "初始高度应不小于最小高度"

    app.add_track()
    h2 = app.scaled_win_height
    print(f"添加第2条轨道后高度: {h2}")
    assert h2 > base_height, "添加轨道后高度应增加"
    assert h2 >= app._get_minimum_height(), "高度应不小于最小高度"

    app.add_track()
    h3 = app.scaled_win_height
    print(f"添加第3条轨道后高度: {h3}")
    assert h3 > h2, "添加轨道后高度应继续增加"

    app.active_track_index = 2
    app._remove_active_track()
    h_after_remove = app.scaled_win_height
    print(f"删除1条轨道后高度: {h_after_remove}")
    assert h_after_remove < h3, "删除轨道后高度应减小"
    assert h_after_remove >= app._get_minimum_height(), "高度应不小于最小高度"
    print("[PASS] 高度自动调整测试通过")

    print("=" * 60)
    print("测试2: 左侧面板折叠/展开")
    print("=" * 60)
    original_width = app.scaled_win_width
    print(f"初始窗口宽度: {original_width}")
    assert not app.ops_collapsed, "初始状态应为展开"

    app._toggle_ops_panel()
    collapsed_width = app.scaled_win_width
    print(f"折叠后宽度: {collapsed_width}")
    assert app.ops_collapsed, "折叠后状态应为 collapsed"
    assert collapsed_width < original_width, "折叠后宽度应减小"

    app._toggle_ops_panel()
    expanded_width = app.scaled_win_width
    print(f"展开后宽度: {expanded_width}")
    assert not app.ops_collapsed, "展开后状态应为展开"
    assert expanded_width == original_width, "展开后宽度应恢复"
    print("[PASS] 面板折叠测试通过")

    print("=" * 60)
    print("测试3: 导入多轨道时高度自动调整")
    print("=" * 60)
    base_h = app.scaled_win_height
    print(f"当前高度（2条轨道）: {base_h}")
    app.add_track({"name": "轨道B", "mode": "对轴模式", "nodes": []})
    app.add_track({"name": "轨道C", "mode": "打轴模式", "nodes": []})
    imported_height = app.scaled_win_height
    print(f"再添加2条轨道后高度（共4条）: {imported_height}")
    assert imported_height > base_h, "导入多轨道后高度应增加"
    assert imported_height >= app._get_minimum_height(), "高度应不小于最小高度"
    print("[PASS] 导入高度调整测试通过")

    root.destroy()
    print("=" * 60)
    print("全部测试通过！")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()
