import os
import threading
import yaml
from typing import Any, Callable

from src.qa_web_search import merge_search_sites, parse_search_sites_text


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

    def _set_in_memory(self, key: str, value: Any):
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @property
    def ai_provider(self) -> str:
        return self._data["ai"]["provider"]

    def ai_config(self, provider: str) -> dict:
        return self._data["ai"][provider]

    @property
    def tts_backend(self) -> str:
        return self._data["tts"]["backend"]

    def tts_config(self, backend: str) -> dict:
        return self._data["tts"].get(backend, {})

    @property
    def tts_playback_mode(self) -> str:
        mode = str(self._data.get("tts", {}).get("playback_mode", "")).strip().lower()
        if mode in {"wait", "interrupt", "continue", "fit_wait", "fit_continue"}:
            return mode
        return "continue"

    @property
    def scheduler_interval(self) -> int:
        scheduler_cfg = self._data.get("scheduler", {})
        if "interval" in scheduler_cfg:
            return int(scheduler_cfg["interval"])
        return 1

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
    def capture_use_screenshot(self) -> bool:
        """Global switch first: if capture.use_screenshot is false, always text-only.
        Otherwise falls back to per-provider setting, then True."""
        global_val = self._data.get("capture", {}).get("use_screenshot", True)
        if not global_val:
            return False  # global override: screenshots disabled for all providers
        provider_cfg = self._data.get("ai", {}).get(self.ai_provider, {})
        return bool(provider_cfg.get("use_screenshot", True))

    @property
    def capture_monitor(self) -> int:
        return self._data["capture"].get("monitor", 1)

    @property
    def overlay(self) -> dict:
        return self._data.get("overlay", {})

    @property
    def start_minimized(self) -> bool:
        return self._data.get("app", {}).get("start_minimized", True)

    @property
    def vision_bridge(self) -> dict | None:
        """Return vision_bridge config dict if enabled, else None."""
        cfg = self._data.get("ai", {}).get("vision_bridge", {})
        if not cfg:
            return None
        if not cfg.get("enabled", True):
            return None
        return cfg

    def vision_bridge_provider_config(self) -> tuple[str, dict] | None:
        """Return (provider_name, merged_provider_config) for the vision bridge."""
        bridge = self.vision_bridge
        if bridge is None:
            return None
        provider = bridge["provider"]
        merged = dict(self.ai_config(provider))
        for key, value in bridge.items():
            if key in {"enabled", "provider", "prompt"}:
                continue
            merged[key] = value
        return provider, merged

    @property
    def decision_memory_size(self) -> int:
        return int(self._data.get("ai", {}).get("decision_memory_size", 5))

    @property
    def decision_mode(self) -> str:
        return self._data.get("decision", {}).get("mode", "ai")

    @property
    def rules_config(self) -> dict:
        return self._data.get("decision", {}).get("rules", {})

    @property
    def enabled_plugins(self) -> list[str]:
        plugins_cfg = self._data.get("decision", {}).get("plugins", {})
        enabled = plugins_cfg.get("enabled", [])
        return enabled if isinstance(enabled, list) else []

    def plugin_settings(self, plugin_id: str) -> dict:
        settings = self._data.get("plugin_settings", {}).get(plugin_id, {})
        return settings if isinstance(settings, dict) else {}

    def plugin_setting(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self.plugin_settings(plugin_id).get(key, default)

    def plugin_detail(self, plugin_id: str | None) -> str:
        if plugin_id:
            value = self.plugin_setting(plugin_id, "detail")
            if value is not None:
                return str(value)
        return "normal"

    def plugin_address_by(self, plugin_id: str | None) -> str:
        if plugin_id:
            value = self.plugin_setting(plugin_id, "address_by")
            if value is not None:
                return str(value)
        return "champion"

    def plugin_require_game(self, plugin_id: str | None) -> bool:
        if plugin_id:
            value = self.plugin_setting(plugin_id, "require_game")
            if value is not None:
                return bool(value)
        return True

    def plugin_system_prompt(self, plugin_id: str | None) -> str:
        if plugin_id:
            value = self.plugin_setting(plugin_id, "system_prompt")
            if value is not None:
                return str(value)
        return ""

    def plugin_analysis_trigger(self, plugin_id: str | None) -> dict:
        defaults = {
            "force_after_seconds": 45,
            "hp_drop_pct": 20,
            "gold_delta": 350,
            "cs_delta": 8,
            "skip_stable_cycles": True,
        }
        if not plugin_id:
            return defaults
        result = dict(defaults)
        mapping = {
            "force_after_seconds": "trigger_force_after_seconds",
            "hp_drop_pct": "trigger_hp_drop_pct",
            "gold_delta": "trigger_gold_delta",
            "cs_delta": "trigger_cs_delta",
            "skip_stable_cycles": "trigger_skip_stable_cycles",
        }
        for key, setting_key in mapping.items():
            value = self.plugin_setting(plugin_id, setting_key)
            if value is not None:
                result[key] = value
        return result

    @property
    def qa_settings(self) -> dict:
        settings = self._data.get("qa", {})
        return settings if isinstance(settings, dict) else {}

    @property
    def qa_enabled(self) -> bool:
        return bool(self.qa_settings.get("enabled", False))

    @property
    def qa_mode(self) -> str:
        mode = str(self.qa_settings.get("mode", "ai")).strip().lower()
        if mode in {"ai"}:
            return mode
        return "ai"

    @property
    def qa_system_prompt(self) -> str:
        return str(
            self.qa_settings.get(
                "system_prompt",
                "你是 MOBA 与策略游戏问答助手。用户会在对局中或对局外提出英雄对线、出装、运营、阵容理解等问题。请用简洁、可靠、可执行的中文直接回答，优先给出 2 到 4 个最关键建议；如果信息不够，就明确说明你的假设。",
            )
        )

    @property
    def qa_microphone_backend(self) -> str:
        backend = str(self.qa_settings.get("microphone_backend", "powershell")).strip().lower()
        if backend in {"powershell", "qt"}:
            return backend
        return "powershell"

    @property
    def qa_stt_backend(self) -> str:
        backend = str(self.qa_settings.get("stt_backend", "system")).strip().lower()
        if backend in {"system", "whisper", "funasr"}:
            return backend
        return "system"

    @property
    def qa_funasr_model(self) -> str:
        return str(self.qa_settings.get("funasr_model", "paraformer-zh")).strip() or "paraformer-zh"

    @property
    def qa_microphone_trigger_mode(self) -> str:
        mode = str(self.qa_settings.get("microphone_trigger_mode", "always")).strip().lower()
        if mode in {"always", "hold"}:
            return mode
        return "always"

    @property
    def qa_microphone_hotkey(self) -> str:
        return str(self.qa_settings.get("microphone_hotkey", "alt")).strip()

    @property
    def qa_web_search_enabled(self) -> bool:
        return bool(self.qa_settings.get("web_search_enabled", False))

    @property
    def qa_web_search_engine(self) -> str:
        engine = str(self.qa_settings.get("web_search_engine", "duckduckgo")).strip().lower()
        if engine in {"duckduckgo", "google"}:
            return engine
        return "duckduckgo"

    @property
    def qa_web_search_timeout_seconds(self) -> int:
        return int(self.qa_settings.get("web_search_timeout_seconds", 8) or 8)

    @property
    def qa_web_search_max_results_per_site(self) -> int:
        return int(self.qa_settings.get("web_search_max_results_per_site", 1) or 1)

    @property
    def qa_web_search_max_pages(self) -> int:
        return int(self.qa_settings.get("web_search_max_pages", 3) or 3)

    @property
    def qa_web_search_mode(self) -> str:
        mode = str(self.qa_settings.get("web_search_mode", "auto")).strip().lower()
        if mode in {"off", "auto", "always"}:
            return mode
        return "auto"

    def qa_web_search_sites(self, plugin_id: str | None = None) -> list[dict[str, int | str]]:
        global_sites = parse_search_sites_text(str(self.qa_settings.get("web_search_sites_text", "")))
        plugin_sites = []
        if plugin_id:
            plugin_sites = parse_search_sites_text(str(self.plugin_setting(plugin_id, "qa_search_sites_text", "")))
        merged = merge_search_sites(global_sites, plugin_sites)
        return [{"domain": site.domain, "priority": site.priority} for site in merged]

    @property
    def web_knowledge_settings(self) -> dict:
        settings = self._data.get("web_knowledge", {})
        return settings if isinstance(settings, dict) else {}

    @property
    def web_knowledge_enabled(self) -> bool:
        return bool(self.web_knowledge_settings.get("enabled", False))

    @property
    def web_knowledge_refresh_interval_seconds(self) -> int:
        return int(self.web_knowledge_settings.get("refresh_interval_seconds", 300) or 300)

    @property
    def web_knowledge_search_engine(self) -> str:
        engine = str(self.web_knowledge_settings.get("search_engine", "duckduckgo")).strip().lower()
        if engine in {"duckduckgo", "google"}:
            return engine
        return "duckduckgo"

    @property
    def web_knowledge_timeout_seconds(self) -> int:
        return int(self.web_knowledge_settings.get("timeout_seconds", 8) or 8)

    @property
    def web_knowledge_max_results_per_site(self) -> int:
        return int(self.web_knowledge_settings.get("max_results_per_site", 1) or 1)

    @property
    def web_knowledge_max_pages(self) -> int:
        return int(self.web_knowledge_settings.get("max_pages", 6) or 6)

    @property
    def web_knowledge_always_visible(self) -> bool:
        return bool(self.web_knowledge_settings.get("always_visible", False))

    @property
    def web_knowledge_hotkey(self) -> str:
        return str(self.web_knowledge_settings.get("hotkey", "alt+`")).strip() or "alt+`"

    @property
    def web_knowledge_window_width(self) -> int:
        return int(self.web_knowledge_settings.get("window_width", 560) or 560)

    @property
    def web_knowledge_window_height(self) -> int:
        return int(self.web_knowledge_settings.get("window_height", 900) or 900)

    def plugin_web_knowledge_enabled(self, plugin_id: str | None) -> bool:
        if not plugin_id:
            return False
        value = self.plugin_setting(plugin_id, "knowledge_enabled")
        if value is None:
            return False
        return bool(value)

    @property
    def overwolf(self) -> dict:
        return self._data.get("overwolf", {})

    @property
    def overwolf_required(self) -> bool:
        if not self.overwolf.get("enabled", False):
            return False
        plugin_ids: set[str] = set(self.enabled_plugins)
        plugin_settings = self._data.get("plugin_settings", {})
        if not plugin_ids and isinstance(plugin_settings, dict):
            plugin_ids = {str(key) for key in plugin_settings.keys()}
        for plugin_id in plugin_ids:
            data_source = str(self.plugin_setting(plugin_id, "data_source", "")).strip().lower()
            if data_source in {"overwolf", "hybrid"}:
                return True
        return False

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
        self._set_in_memory(key, value)
        self.save()

    def update_many(self, values: dict[str, Any]):
        for key, value in values.items():
            self._set_in_memory(key, value)
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
