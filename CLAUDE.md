# CLAUDE.md — 明日方舟费用条尺子 & 打轴器

## 项目概述

为《明日方舟》开发的帧数测量与时间轴工具，包含两个独立子程序：

- **ruler/** — 费用条尺子，通过截图分析费用条变化，实时显示当前游戏帧数和计时器
- **timeline_tool/** — 打轴/对轴器，通过 WebSocket 连接尺子获取帧数，支持时间轴编辑与节点提醒

## 技术栈

- Python 3.8+
- tkinter + ttkbootstrap（UI 框架）
- Pillow（图像处理）
- websockets（API 服务端/客户端）
- pystray（系统托盘）
- winsound（Windows 声音提醒）

## 架构概览

```
ruler/
├── main.py                   # 主入口，分析工作线程，UI 消息循环
├── overlay_window.py         # 悬浮窗 UI
├── calibration_manager.py    # 校准数据管理
├── config_manager.py         # 配置文件读写
├── utils.py                  # 费用条 ROI 查找 + 帧数判定
├── api_server.py             # WebSocket API 服务端
├── logger_setup.py           # 日志系统
└── controllers/
    ├── base.py               # 截图控制器基类
    ├── mumu.py               # MuMu模拟器12 截图增强
    ├── ldplayer.py           # 雷电模拟器9 截图增强
    └── minicap.py            # 通用 Minicap 截图方案

timeline_tool/
├── main.py                   # 主入口，DPI 感知设置，支持重启后自动加载
├── app.py                    # 主应用类 TimelineApp，WS 队列处理，UI 布局
├── timeline_track.py         # 单轨道类 TimelineTrack，绘制/节点/提醒
├── config.py                 # 配置常量（v0.7），字体/颜色/尺寸/网络
├── file_io.py                # 时间轴文件的读写（JSON）
├── websocket_client.py       # WebSocket 客户端，连接尺子 API
├── naming_manager.py         # 保存时规范化命名配置管理
├── naming_dialog.py          # 保存时命名填写对话框
├── naming_config.json        # 命名配置：启用开关、字段定义
├── utils.py                  # 资源路径、帧时间格式化、日志
├── operator_portrait_manager.py  # 干员头像扫描/加载/昵称映射/缓存
├── operator_aliases.xlsx     # 干员昵称映射表（第一列标准名称，后续列别名）
└── operator_portraits/       # 干员头像图片（编号_名称.png）
```

## 关键依赖关系

- **尺子是打轴器的前置条件** — timeline_tool 通过 WebSocket（默认 `ws://localhost:2606`）从 ruler 获取实时帧数
- 尺子默认启动 API 端口 2606
- 打轴器版本：v0.7

## 修改记录

### 2026-06-01 — 打轴器大规模重构（Claude Code 会话）

#### v0.7 之前的三项优化
1. **精确帧显示** — `timeline_track.py:163-167`
2. **自定义窗口高度 + 文字避让** — `app.py:446-456`、`timeline_track.py:247-288`
3. **多时间轴支持** — `app.py:52-54`、`app.py:191-248`

#### 本次会话修改

4. **保存模式固定为对轴** — `timeline_track.py:111`
   - `dump_data()` 中 `mode` 字段始终返回 `"对轴模式"`，不再保存当前 UI 模式

5. **全部打轴/全部对轴按钮** — `app.py`
   - 从顶部栏移至左侧 ops_frame，位于模式切换按钮上方
   - 仅当轨道数 > 1 时显示，单轨道自动隐藏

6. **单轴独立闪烁** — `timeline_track.py` + `app.py`
   - 移除全局窗口闪烁，改为每个轨道独立闪烁自己的 canvas 背景（`#21252b` ↔ `#5c2a2a`）

7. **窗口拖动重构** — `app.py`
   - 顶部栏最左侧添加专用拖动手柄按钮 `⋮⋮`（cursor="fleur"）
   - 改用屏幕坐标 `event.x_root/y_root` 避免抖动
   - canvas 返回 `"break"` 阻止事件冒泡

8. **默认文件名格式** — `file_io.py:67-69`
   - 从手动输入改为自动 `#mmddHHMM_Xo`（时间戳 + 轨道数）

9. **文字避让修复** — `timeline_track.py:259`
   - 排序条件 `frame > center_frame` → `frame >= center_frame`
   - 节点所在帧及之前优先显示该节点名称

10. **最小窗口高度修复** — `config.py:9` + `app.py:294`
    - `MIN_WINDOW_HEIGHT` 从 80 增加到 140
    - `_adjust_window_height` 乘以 scaling_factor 并考虑 ops_frame 最小需求

11. **重启按钮** — `app.py` + `main.py`
    - 顶部栏最右侧箭头图标，点击确认后保存当前轴并重启进程
    - 新进程通过环境变量 `TIMELINE_AUTOLOAD` 自动恢复相同时间轴

12. **轨道默认命名** — `app.py:217` + `timeline_track.py`
    - 新建轨道自动命名为 `轨道0`、`轨道1`、`轨道2`...
    - 按钮文本改为"新建轨道"/"删除轨道"

13. **保存时规范化命名对话框** — 新增 `naming_manager.py`、`naming_dialog.py`、`naming_config.json`
    - 配置文件 `naming_config.json` 控制启用开关和字段定义
    - 启用后点击保存弹出填写窗口，字段默认值自动填入（轨道数、时间戳自动计算）
    - 确认后自动用 `_` 连接各字段合成文件名
    - 关闭方式：将 `naming_config.json` 中 `"enabled"` 改为 `false`

### 2026-06-01 — 最小高度优化 + 双轴 resize 把手

14. **降低最小窗口高度** — `config.py:9` + `app.py`
    - `MIN_WINDOW_HEIGHT` 从 140 降至 100
    - `_adjust_window_height` 中 `ops_min_h` 从 130 降至 100（下侧退出按钮已删除，ops_frame 所需空间减少）

15. **双轴 resize 把手** — `app.py`
    - 替换之前不完善的青色底部细条，改为更明确的两个拖拽把手：
      - **底部** `━━`（双横线）— 调整窗口高度，位于 tracks 区域下方
      - **右侧** `┃┃`（双竖线）— 调整窗口宽度，位于内容区域最右侧
    - 两者使用暗色背景 `#3e4451`，低调不抢视觉焦点
    - 新增 `_on_resize_height_start/_motion` 和 `_on_resize_width_start/_motion` 处理对应拖拽逻辑
    - 宽度调整时同步更新 `ops_frame` 宽度，保持 1:3 比例

### 2026-06-01 — 节点预告 + 吸附逻辑 + UI 布局修复

16. **打包文件夹名称同步** — `build.py`
    - 正常版：`费用尺+打轴器_卓越特供版_YYYYMMDD`
    - Debug 版：`费用尺+打轴器_卓越特供版_YYYYMMDD_debug版`

17. **路径输入去引号** — `ruler/config_manager.py`
    - 首次配置向导中，模拟器安装路径自动去除首尾 `"` 引号

18. **底部 resize 把手位置修复** — `app.py`
    - 根因：`expand=True` 的 `content_frame` 先 pack，抢占了全部空间，导致 `bottom_resize_handle` 被挤出可视区域
    - 修复：调整 pack 顺序为 `track_selector_frame` → `bottom_resize_handle` → `content_frame`(expand)

19. **info_frame 布局重构** — `timeline_track.py`
    - 根因：`canvas` 先 pack 且 `expand=True`，抢占 `self.frame` 全部空间，后 pack 的 `info_frame` 被挤出底部边界
    - 修复：pack 顺序改为 `title_bar`(TOP) → `info_frame`(BOTTOM) → `canvas`(expand)
    - `info_frame` 内部从 `pack` 改为 `grid`，预告列设置 `minsize`，防止被挤出

20. **节点预告功能** — `timeline_track.py`
    - 对轴模式下，当下个节点进入警报范围时，`info_remaining_label` 显示 `还剩{x}帧`
    - 预告始终基于 `current_next_node`，不受光标附近节点干扰
    - 支持多轨道同时预告

21. **节点名称截断** — `timeline_track.py`
    - `info_name_label` 中节点名称超过 10 字符自动截断并显示 `…`，防止与时间标签重叠

22. **全部对轴强制吸附，打轴不改变吸附** — `app.py`
    - `_set_all_tracks_mode_following`：强制所有轨道 `magnet_mode=True`
    - `_set_all_tracks_mode_editing` 与打轴模式切换：不再改变 `magnet_mode`，保持用户手动设置

23. **时间流逝时强制吸附锁定** — `app.py`
    - 基于 `current_game_frame` 是否增加判断时间是否流逝
    - 时间流逝时：对轴轨道强制恢复吸附并 `magnet_locked=True`，拖动无法解除
    - 时间暂停或尺子未运行时：解除 `magnet_locked`

### 2026-06-01 — 干员头像替换

24. **干员头像目录与昵称映射** — 新增 `operator_portraits/`、`operator_aliases.xlsx`、`operator_portrait_manager.py`
    - `operator_portraits/`：存放 417 张干员头像，命名格式 `编号_名称.png`
    - `operator_aliases.xlsx`：第一列为标准名称，同一行后续列为该名称的多个别名/昵称
    - `OperatorPortraitManager`：扫描目录、加载 Excel 映射、缓存缩放后的 PhotoImage

25. **节点名称头像替换** — `timeline_track.py`
    - 节点名称中输入 `[编号/名称/昵称]` 时，自动替换为对应干员头像
    - 解析后的剩余文字与头像水平并排显示
    - 头像中心 (`anchor="center"`) 与文字顶部齐平，允许向上覆盖时间轴轨道
    - 头像尺寸与文字高度协调（`portrait_size = max(20, int(22 * scaling_factor))`）

### 2026-06-02 — 打包后干员头像失效修复

26. **路径计算适配 PyInstaller** — `operator_portrait_manager.py`
    - 根因：`_MEIPASS` 临时目录中不包含 `operator_portraits/` 和 `operator_aliases.xlsx`
    - 修复：新增 `_get_resource_dir()`，打包后（`sys.frozen`）返回 `sys.executable` 所在目录（exe 同级）

27. **打包脚本补充外部资源** — `build.py`
    - `copy_extra_files()` 中增加 `operator_aliases.xlsx` 和 `operator_portraits/` 的复制
    - 作为外部资源放在 exe 同级，方便用户自定义头像和昵称映射

### 文件约定

- 代码注释和文档使用中文
- 日志输出使用中文
- 变量名、函数名使用英文
- 所有图标来自 Google Material Symbols

### 2026-06-02 — 修复 AnalysisWorker 异常捕获缺失 + 提权逻辑漏洞

28. **捕获 `subprocess.CalledProcessError`** — `ruler/main.py`
    - 根因：`ldplayer.py` / `minicap.py` 中使用 `subprocess.run(..., check=True)`，当 adb/dnconsole 命令返回非零退出码时抛出 `subprocess.CalledProcessError`
    - 该异常未被 `analysis_worker` 的 `except` 捕获，导致工作线程无声崩溃，错误信息不进入日志文件
    - 修复：增加 `import subprocess`，并将 `subprocess.CalledProcessError` 加入异常捕获列表，确保命令失败时错误能被正确记录并提示用户

29. **修复管理员提权逻辑** — `ruler/main.py:337-353`
    - 根因：`ShellExecuteW("runas")` 成功返回后，原进程没有调用 `sys.exit(0)` 退出，导致**非管理员老进程继续运行**
    - 后果：用户看到的是提权后的新进程窗口，但后台实际运行的仍是未提权的老进程；老进程调用 `dnconsole.exe` 时触发 `OSError: [WinError 740]`（操作需要提升权限），分析线程崩溃
    - 修复：
      1. 检查 `ShellExecuteW` 返回值（`<=32` 表示失败），失败时提示用户手动以管理员身份运行
      2. 提权请求成功发出后，原进程立即 `sys.exit(0)`，确保只有新进程继续执行

30. **费用尺 exe 强制管理员启动** — `build.py`
    - 根因：原版费用尺的 exe manifest 中嵌入了 `requireAdministrator`，双击自动弹出 UAC；当前 `build.py` 未使用 `--uac-admin`
    - 修复：`build_exe()` 新增 `uac_admin` 参数，费用尺打包时传入 `uac_admin=True`，PyInstaller 会在 exe manifest 中嵌入 `requireAdministrator`
    - 打轴器不需要管理员权限，不开启此选项

31. **修复浏览按钮路径无法回填** — `ruler/config_manager.py`
    - 根因：`ConfigWindow` 调用了 `self.grab_set()` 设为模态窗口，`filedialog.askdirectory()` 也是模态对话框，两者 grab 冲突导致 `askdirectory` 返回空字符串
    - 修复：打开 `askdirectory` 前调用 `self.grab_release()` 临时释放模态，关闭后 `self.grab_set()` 恢复；同时为 `askdirectory` 显式传入 `parent=self`

### 2026-06-02 — 命名配置重构 + 打轴器 UI 优化

32. **命名配置支持多预设** — `timeline_tool/naming_config.json` + `naming_manager.py` + `naming_dialog.py` + `app.py`
    - `naming_config.json` 从单 `fields` 数组改为 `presets` 数组结构，支持"极简"/"日常"/"合约"三种命名规则
    - 新增 `default_preset` 字段，可配置默认展示的预设（当前设为"合约"）
    - `naming_manager.py` 新增 `get_presets()` / `get_preset_fields()` / `get_all_presets()` / `get_default_preset()`
    - `naming_dialog.py` 顶部新增预设导航栏，点击切换字段表单；说明字体从 `-9` 加大到 `9`
    - `naming_config.json` 作为外部资源放在 exe 同级，用户可直接用记事本修改

33. **轨道高度自动调整优化** — `timeline_tool/app.py`
    - `_get_minimum_height()` 保持原始保守值不变（`TRACK_MIN_HEIGHT = 50`，`ops_min_h = 80`），仅用于限制手动拖拽时的最小高度
    - `_adjust_window_height()` 改为**直接计算合适高度**：每个轨道固定分配约 90px，不依赖 `_get_minimum_height()`，确保新建/删除/导入时窗口高度能完整容纳所有轨道内容

33. **左侧操作面板折叠按钮** — `timeline_tool/app.py`
    - 在顶部栏重启按钮左侧新增 `◀`/`▶` 折叠按钮
    - 点击后隐藏/显示 `ops_frame`，窗口宽度同步减小/恢复
    - 修复 pack 顺序：折叠按钮 `pack` 在重启按钮之后，确保视觉位置在重启按钮左侧
    - 修复展开后位置错乱：`pack()` 时传入 `before=self.tracks_grip_frame`，确保 `ops_frame` 始终排在轨道区域左侧
    - 按钮 tooltip 随状态切换显示"隐藏操作面板"/"展开操作面板"
    - 折叠后最小宽度修正：新增 `_get_minimum_width()`，隐藏后最小宽度降为 `WINDOW_WIDTH * 2/3`，避免拖拽时窗口被强制拉回原宽度
    - 展开宽度恢复修正：折叠时记录 `_expanded_width`，展开时直接恢复该值，避免加减 `_ops_width` 导致宽度计算错误
    - 折叠时同步隐藏顶部"新建轨道"/"删除轨道"按钮，展开时恢复（使用 `before=self.track_buttons_frame` 确保 pack 顺序正确）
    - 重启功能修复：`app.py` 中 `_restart_app` 区分打包模式（`sys.frozen` 时直接启动 exe）和开发模式（启动 main.py）
    - 重启崩溃根因：PyInstaller `--onefile` 模式下，父子进程并行解压到临时目录，父进程退出后立即清理自己的临时目录，子进程尚未完成解压，导致 `init.tcl` / `auto.tcl` 等文件访问失败
    - 修复：
      1. 从环境变量副本中剔除 `_MEIPASS2`、`TCL_LIBRARY`、`TK_LIBRARY`
      2. 添加 `CREATE_NEW_PROCESS_GROUP` 标志确保子进程独立
      3. 原进程启动子进程后先隐藏窗口，等待 1 秒让子进程完成解压，再退出
    - 命名对话框修复：`naming_dialog.py` 改用 `bootstyle` 替代 `style` 避免 ttkbootstrap 样式兼容问题；窗口高度改为动态计算（`self.winfo_reqheight()`）；切换预设后调用 `update_idletasks()` 强制刷新布局

34. **打包脚本编码修复** — `build.py`
    - 根因：Windows GBK 终端打印 `operator_portraits/` 中生僻字文件名时 `UnicodeEncodeError`
    - 修复：`main()` 开头调用 `sys.stdout.reconfigure(encoding='utf-8')`

### 2026-06-02 — 修复打轴器编辑/导入后无法重启

35. **`dump_data()` 返回深拷贝** — `timeline_track.py`
    - 根因推测：`self.timeline_data` 直接作为引用返回，外部修改或 JSON 序列化时可能受引用关系影响
    - 修复：`"nodes": copy.deepcopy(self.timeline_data)`，确保导出数据完全独立

36. **`_setup_ui` 重复代码清理** — `timeline_track.py`
    - 根因：`_setup_ui` 中 `info_time_label` 等 widget 被重复创建两次（第 69-88 行与第 101-113 行）
    - 修复：删除第 96-113 行的重复创建代码

37. **`_restart_app` 健壮性增强** — `app.py`
    - 新增 `_json.dumps` 序列化预检查，防止不可序列化数据导致静默失败
    - 所有异常捕获点增加 `messagebox.showerror`，用户能立即看到错误原因
    - `self.root.quit()` 改为 `self.root.destroy()`，彻底释放 tkinter 资源，确保原进程干净退出
    - `child_env` 增加 `{k: str(v) for k, v in child_env.items()}` 防御性处理，确保环境变量值均为字符串
    - 清除列表增加 `_MEIPASS`，防止 PyInstaller 子进程继承父进程临时目录
    - 新增详细诊断日志，记录每个轨道的节点数和首尾节点信息，便于排查数据流问题
    - 新增未保存修改确认：若 `_dirty=True`，重启前弹出与关闭窗口类似的确认对话框

38. **`_do_autoload` 诊断增强** — `app.py`
    - 新增文件存在性检查，若临时文件不存在则直接创建默认轨道
    - 加载前后记录详细日志，包括轨道数、节点数、首尾节点信息
    - 异常日志增加 `exc_info=True`，保留完整堆栈

39. **`_restart_app` 等待时间延长** — `app.py`
    - `time.sleep(1)` 延长至 `time.sleep(3)`，给 PyInstaller onefile 子进程更充分的解压和启动时间
    - 避免父进程过早退出导致子进程因临时目录竞争而崩溃

### 2026-06-03 — 修复不能连续重启两次的bug

40. **`_restart_app` 子进程存活检测 + CREATE_BREAKAWAY_FROM_JOB** — `app.py`
    - 根因推测：Windows Job Object 可能在父进程退出时连带终止子进程，导致第二次重启后子进程无声消失；或子进程启动后因某种原因立即崩溃，原进程无感知
    - 修复：
      1. `subprocess.Popen` 捕获返回的进程对象 `proc`，记录 PID 便于诊断
      2. 添加 `CREATE_BREAKAWAY_FROM_JOB` (0x01000000) 标志，尝试让子进程脱离 Windows Job Object；若失败则回退到仅 `CREATE_NEW_PROCESS_GROUP`
      3. `time.sleep(10)` 改为分步等待（每秒检查一次），期间调用 `proc.poll()` 检测子进程是否已异常退出；若退出则调用 `self.root.deiconify()` 恢复窗口，并弹出 `messagebox.showerror` 提示用户
      4. 所有异常路径增加详细日志，避免静默失败

41. **`setup_logging()` 使用 `resource_path()` 导致日志丢失** — `timeline_tool/utils.py`
    - 根因：误用 `resource_path()` 计算日志目录。该函数在 PyInstaller onefile 模式下返回 `_MEIPASS` 临时目录，而临时目录在程序退出时会被 bootloader 清理，导致日志文件被删除
    - 修复：新增 `_get_log_dir()` 函数，打包模式使用 `os.path.dirname(sys.executable)`（exe 同级目录），开发模式使用项目根目录，确保日志持久保存

42. **`_restart_app` 子进程存活检测 + CREATE_BREAKAWAY_FROM_JOB** — `app.py`
    - 根因推测：Windows Job Object 可能在父进程退出时连带终止子进程，导致第二次重启后子进程无声消失；或子进程启动后因某种原因立即崩溃，原进程无感知
    - 修复：
      1. `subprocess.Popen` 捕获返回的进程对象 `proc`，记录 PID 便于诊断
      2. 添加 `CREATE_BREAKAWAY_FROM_JOB` (0x01000000) 标志，尝试让子进程脱离 Windows Job Object；若失败则回退到仅 `CREATE_NEW_PROCESS_GROUP`
      3. `time.sleep(10)` 改为分步等待（每秒检查一次），期间调用 `proc.poll()` 检测子进程是否已异常退出；若退出则调用 `self.root.deiconify()` 恢复窗口，并弹出 `messagebox.showerror` 提示用户
      4. 所有异常路径增加详细日志，避免静默失败

43. **子进程正常退出误报修复** — `app.py`
    - 根因：分步等待中 `proc.poll()` 返回 0（子进程正常退出）时，原代码仍当作异常退出弹窗提示
    - 修复：区分返回码，`ret == 0` 时记录为正常退出并跟随退出，不再弹窗；仅 `ret != 0` 时才弹窗报异常

44. **PyInstaller onefile 子进程启动参数重构** — `app.py` + `main.py`
    - 根因：`close_fds=True` 关闭了 PyInstaller bootloader 解压归档所需的可继承句柄，导致子进程在 Python 代码执行前即崩溃；`CREATE_BREAKAWAY_FROM_JOB` 可能触发 `CreateProcess` 失败并弹窗打扰用户；`TCL_LIBRARY`/`TK_LIBRARY` 被强制删除后反而干扰 PyInstaller runtime hook 的正常行为
    - 修复：
      1. `app.py` 去掉 `close_fds=True`，让 bootloader 正常继承所需句柄
      2. 去掉 `CREATE_BREAKAWAY_FROM_JOB`，只保留 `CREATE_NEW_PROCESS_GROUP` 防止 CTRL+C 信号传递
      3. 环境变量只删 `_MEIPASS2`，其余交由 PyInstaller runtime hook 自行处理
      4. `main.py` 异常捕获后增加 `sys.exit(1)`，确保崩溃时返回非零码，父进程能正确识别

45. **重启功能重构：不保留编辑、重新打开原文件** — `app.py` + `main.py` + `file_io.py`
    - 需求变更：重启不再通过临时文件保存内存中的编辑内容；如果之前打开了某个文件，重启后直接重新加载该文件；如果有未保存修改，提示用户
    - 修改：
      1. `file_io.py`：`load_timeline_from_file` 返回 `(data, filepath)` 元组；`save_timeline_to_file` 返回 `(ok, filepath)` 元组；新增 `_load_from_path(filepath)` 内部函数用于不弹对话框加载
      2. `app.py`：新增 `self._current_file` 记录当前打开的文件路径；`TimelineApp.__init__` 增加 `open_file` 参数；新增 `_load_file(filepath)` 和 `_load_file_data(data, filepath)` 方法；`_restart_app` 完全重写：根据 `_dirty` 和 `_current_file` 组合四种提示文案，不再写临时文件，通过 `TIMELINE_OPEN_FILE` 环境变量传递原文件路径；`_load_timeline` 和 `_save_timeline` 更新以记录文件路径
      3. `main.py`：检查 `TIMELINE_OPEN_FILE` 环境变量并传递给 `TimelineApp`

46. **窗口高度自动调整增大** — `app.py`
    - 需求：新建/删除轨道时自动计算的窗口高度偏小，内容显示拥挤
    - 修改：`_adjust_window_height()` 中 `per_track` 从 `90` 增至 `120`，`ops_min_h` 从 `80` 增至 `100`，给轨道内容（title_bar + canvas + info_frame）留出更充裕的垂直空间
