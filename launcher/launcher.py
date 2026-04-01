from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
CONFIG_EXAMPLE_PATH = ROOT / "config.example.yaml"


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def log(message: str) -> None:
    print(f"[{now_text()}] [launcher] {message}", flush=True)


@dataclass
class WatchedGame:
    game_id: str
    process_names: list[str] = field(default_factory=list)


@dataclass
class LauncherConfig:
    enabled: bool = False
    poll_interval: float = 2.0
    cooldown_seconds: float = 60.0
    auto_start_overwolf: bool = True
    auto_start_main: bool = True
    auto_stop_main: bool = False
    auto_stop_overwolf: bool = False
    main_python: str = ".\\.venv\\Scripts\\python.exe"
    main_args: list[str] = field(default_factory=lambda: ["main.py"])
    overwolf_method: str = "auto"
    overwolf_path: str = ""
    overwolf_protocol: str = "overwolf://"
    watched_games: list[WatchedGame] = field(default_factory=list)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> LauncherConfig:
    raw = load_yaml(CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH)
    section = raw.get("launcher", {}) or {}
    overwolf = section.get("overwolf", {}) or {}
    watched = section.get("watched_games", []) or []
    watched_games = [
        WatchedGame(
            game_id=str(item.get("id", "unknown")),
            process_names=[str(name) for name in (item.get("process_names", []) or []) if str(name).strip()],
        )
        for item in watched
    ]
    return LauncherConfig(
        enabled=bool(section.get("enabled", False)),
        poll_interval=float(section.get("poll_interval", 2)),
        cooldown_seconds=float(section.get("cooldown_seconds", 60)),
        auto_start_overwolf=bool(section.get("auto_start_overwolf", True)),
        auto_start_main=bool(section.get("auto_start_main", True)),
        auto_stop_main=bool(section.get("auto_stop_main", False)),
        auto_stop_overwolf=bool(section.get("auto_stop_overwolf", False)),
        main_python=str(section.get("main_python", ".\\.venv\\Scripts\\python.exe")),
        main_args=[str(arg) for arg in (section.get("main_args", ["main.py"]) or ["main.py"])],
        overwolf_method=str(overwolf.get("method", "auto")),
        overwolf_path=str(overwolf.get("path", "")),
        overwolf_protocol=str(overwolf.get("protocol", "overwolf://")),
        watched_games=watched_games,
    )


def query_processes() -> list[dict[str, Any]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Depth 3"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        log(f"process query failed: {result.stderr.strip() or result.stdout.strip()}")
        return []
    text = result.stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log("process query returned invalid JSON")
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def find_matching_games(processes: list[dict[str, Any]], watched_games: list[WatchedGame]) -> list[str]:
    active: list[str] = []
    names = {str(p.get("Name", "")).lower() for p in processes}
    for item in watched_games:
        if any(proc.lower() in names for proc in item.process_names):
            active.append(item.game_id)
    return active


def is_overwolf_running(processes: list[dict[str, Any]]) -> bool:
    names = {str(p.get("Name", "")).lower() for p in processes}
    return "overwolf.exe" in names or "overwolfbrowser.exe" in names


def is_main_running(processes: list[dict[str, Any]]) -> bool:
    for proc in processes:
        name = str(proc.get("Name", "")).lower()
        cmd = str(proc.get("CommandLine", "") or "").lower()
        if name.startswith("python") and "main.py" in cmd:
            return True
    return False


def find_python_executable(config: LauncherConfig) -> str:
    candidate = (ROOT / config.main_python).resolve() if not os.path.isabs(config.main_python) else Path(config.main_python)
    if candidate.exists():
        return str(candidate)
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def start_main(config: LauncherConfig) -> None:
    python_exe = find_python_executable(config)
    args = [python_exe, *config.main_args]
    subprocess.Popen(args, cwd=str(ROOT))
    log(f"started main process: {' '.join(args)}")


def start_overwolf(config: LauncherConfig) -> None:
    method = config.overwolf_method.lower()
    if method == "path" and config.overwolf_path:
        subprocess.Popen([config.overwolf_path], cwd=str(ROOT))
        log(f"started overwolf via path: {config.overwolf_path}")
        return
    if method == "protocol":
        os.startfile(config.overwolf_protocol)
        log(f"started overwolf via protocol: {config.overwolf_protocol}")
        return

    auto_paths = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Overwolf" / "OverwolfLauncher.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Overwolf" / "OverwolfLauncher.exe",
        Path.home() / "AppData" / "Local" / "Overwolf" / "OverwolfLauncher.exe",
    ]
    for path in auto_paths:
        if str(path) and path.exists():
            subprocess.Popen([str(path)], cwd=str(ROOT))
            log(f"started overwolf via auto path: {path}")
            return

    os.startfile(config.overwolf_protocol)
    log(f"started overwolf via fallback protocol: {config.overwolf_protocol}")


def stop_main(processes: list[dict[str, Any]]) -> None:
    for proc in processes:
        name = str(proc.get("Name", "")).lower()
        cmd = str(proc.get("CommandLine", "") or "").lower()
        pid = proc.get("ProcessId")
        if name.startswith("python") and "main.py" in cmd and pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True, text=True)
            log(f"stopped main process pid={pid}")


def stop_overwolf(processes: list[dict[str, Any]]) -> None:
    for proc in processes:
        name = str(proc.get("Name", "")).lower()
        pid = proc.get("ProcessId")
        if name in {"overwolf.exe", "overwolfbrowser.exe"} and pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True, text=True)
            log(f"stopped overwolf process pid={pid}")


class LauncherState:
    def __init__(self) -> None:
        self.last_games: list[str] = []
        self.cooldown_deadline: float | None = None


def run_launcher(config: LauncherConfig) -> None:
    state = LauncherState()
    log("launcher started")
    while True:
        processes = query_processes()
        active_games = find_matching_games(processes, config.watched_games)
        overwolf_running = is_overwolf_running(processes)
        main_running = is_main_running(processes)

        if active_games:
            if active_games != state.last_games:
                log(f"detected games: {', '.join(active_games)}")
            state.cooldown_deadline = None

            if config.auto_start_overwolf and not overwolf_running:
                start_overwolf(config)

            if config.auto_start_main and not main_running:
                start_main(config)
        else:
            if state.last_games and state.cooldown_deadline is None:
                state.cooldown_deadline = time.time() + config.cooldown_seconds
                log(f"games disappeared, entering cooldown for {int(config.cooldown_seconds)}s")
            elif state.cooldown_deadline is not None and time.time() >= state.cooldown_deadline:
                if config.auto_stop_main and main_running:
                    stop_main(processes)
                if config.auto_stop_overwolf and overwolf_running:
                    stop_overwolf(processes)
                state.cooldown_deadline = None

        state.last_games = active_games
        time.sleep(max(0.5, config.poll_interval))


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-launch Overwolf and LOL Coach when watched games start.")
    parser.add_argument("--once", action="store_true", help="Run one detection cycle and exit.")
    args = parser.parse_args()

    config = load_config()
    if not config.enabled:
        log("launcher.enabled is false; nothing to do")
        return 0
    if not config.watched_games:
        log("no watched games configured")
        return 1

    if args.once:
        processes = query_processes()
        games = find_matching_games(processes, config.watched_games)
        log(f"active games: {games or 'none'}")
        log(f"overwolf running: {is_overwolf_running(processes)}")
        log(f"main running: {is_main_running(processes)}")
        return 0

    try:
        run_launcher(config)
    except KeyboardInterrupt:
        log("launcher stopped")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
