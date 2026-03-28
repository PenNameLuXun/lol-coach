import os
import threading
import yaml
from typing import Any, Callable


class Config:
    def __init__(self, path: str = "config.yaml"):
        self._path = path
        self._data: dict = {}
        self._callbacks: list[Callable] = []
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._mtime: float = 0.0
        self._load()

    def _load(self):
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        self._mtime = self._current_mtime()

    def _current_mtime(self) -> float:
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True)
        self._mtime = self._current_mtime()

    @property
    def ai_provider(self) -> str:
        return self._data["ai"]["provider"]

    @property
    def system_prompt(self) -> str:
        return self._data["ai"]["system_prompt"]

    def ai_config(self, provider: str) -> dict:
        return self._data["ai"][provider]

    @property
    def tts_backend(self) -> str:
        return self._data["tts"]["backend"]

    def tts_config(self, backend: str) -> dict:
        return self._data["tts"].get(backend, {})

    @property
    def tts_interrupt(self) -> bool:
        return self._data["tts"].get("interrupt", True)

    @property
    def capture_interval(self) -> int:
        return self._data["capture"]["interval"]

    @property
    def capture_hotkey(self) -> str:
        return self._data["capture"].get("hotkey", "")

    @property
    def capture_region(self) -> str:
        return self._data["capture"].get("region", "fullscreen")

    @property
    def capture_jpeg_quality(self) -> int:
        return self._data["capture"].get("jpeg_quality", 85)

    @property
    def capture_monitor(self) -> int:
        return self._data["capture"].get("monitor", 1)

    @property
    def overlay(self) -> dict:
        return self._data.get("overlay", {})

    @property
    def lol_client_detail(self) -> str:
        return self._data.get("lol_client", {}).get("detail", "normal")

    @property
    def start_minimized(self) -> bool:
        return self._data.get("app", {}).get("start_minimized", True)

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation access e.g. 'capture.interval'"""
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any):
        """Dot-notation write + save e.g. set('capture.interval', 10)"""
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    def on_reload(self, callback: Callable):
        self._callbacks.append(callback)

    def _start_watcher(self):
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def _stop_watcher(self):
        self._stop_event.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=3)

    def _watch_loop(self):
        while not self._stop_event.wait(timeout=1.0):
            mtime = self._current_mtime()
            if mtime != self._mtime:
                self._load()
                for cb in self._callbacks:
                    cb()
