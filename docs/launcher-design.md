# Launcher Design

## Goal

增加一层独立守护启动器，用来在检测到目标游戏进程后自动编排：

- Overwolf
- `main.py`

它不负责业务逻辑，也不负责教练规则，只负责进程生命周期管理。

## Why Separate Launcher

不要把“发现游戏并拉起外部进程”的职责放进 `main.py`：

- `main.py` 是被拉起的业务进程
- Overwolf 是独立运行环境
- 进程编排更适合作为外层守护器

## Runtime Model

```text
Launcher
  -> detect watched game processes
  -> start Overwolf if needed
  -> start main.py if needed
  -> monitor running state
  -> optional cooldown
  -> optional stop main / Overwolf
```

## State Machine

- `idle`
  - 没检测到目标游戏

- `game_detected`
  - 检测到至少一个 watched game 进程

- `running`
  - Overwolf / `main.py` 已按需拉起

- `cooldown`
  - 游戏消失后先等待一段时间，避免重连或窗口切换误判

## Detection Strategy

当前优先使用：

- Windows `Win32_Process`

原因：

- 不需要额外安装 `psutil`
- 能同时拿到：
  - 进程名
  - 可执行路径
  - 命令行

这样既能检测游戏，也能判断 `main.py` 是否已经启动。

## Configuration

通过 `config.yaml` / `config.example.yaml` 的 `launcher` 段控制：

- `enabled`
- `poll_interval`
- `cooldown_seconds`
- `auto_start_overwolf`
- `auto_start_main`
- `auto_stop_main`
- `auto_stop_overwolf`
- `main_python`
- `main_args`
- `overwolf.method`
- `overwolf.path`
- `overwolf.protocol`
- `watched_games`

## Current Scope

当前版本先解决：

- 检测 LoL/TFT 客户端生态进程
- 自动拉起 Overwolf
- 自动拉起 `main.py`
- 冷却期和可选自动关闭

后续可继续扩展：

- 结合插件 `is_available()` 做更智能的游戏判定
- 记录 launcher 日志到文件
- 做成托盘程序或 Windows 开机自启任务
