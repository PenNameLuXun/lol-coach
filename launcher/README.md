# Launcher

独立启动器，负责在检测到目标游戏进程后按配置自动拉起：

- `Overwolf`
- `main.py`

它不替代主程序，也不侵入主程序逻辑，而是作为外层守护进程存在。

## 运行

```powershell
python launcher/launcher.py
```

如果你在项目根目录下已经有 `.venv`，更推荐：

```powershell
.\.venv\Scripts\python launcher/launcher.py
```

## 配置

配置位于根目录 `config.yaml` 或模板 `config.example.yaml` 的 `launcher` 段。

关键配置：

- `launcher.enabled`
- `launcher.poll_interval`
- `launcher.cooldown_seconds`
- `launcher.auto_start_overwolf`
- `launcher.auto_start_main`
- `launcher.auto_stop_main`
- `launcher.auto_stop_overwolf`
- `launcher.main_python`
- `launcher.main_args`
- `launcher.overwolf.method`
- `launcher.overwolf.path`
- `launcher.overwolf.protocol`
- `launcher.watched_games`

## 当前设计

- 通过 `Win32_Process` 查询当前进程和命令行
- 通过配置里的 `watched_games[].process_names` 判断目标游戏是否启动
- 发现目标游戏后：
  - 按需启动 Overwolf
  - 按需启动 `main.py`
- 游戏退出后进入冷却期
- 冷却期结束后可选关闭：
  - `main.py`
  - Overwolf

## 注意

- LoL 与 TFT 当前通常共用同一套客户端进程，所以默认规则按 LoL 生态进程做检测
- 如果你的本地 Overwolf 安装路径特殊，建议显式填写 `launcher.overwolf.path`
- 启动器本身不会修改主程序内部状态，只负责进程编排
