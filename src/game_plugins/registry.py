from __future__ import annotations

import importlib
import inspect
import pkgutil

import src.game_plugins as game_plugins_pkg
from src.game_plugins.base import GamePlugin


class PluginRegistry:
    def __init__(self):
        self._plugins: list[GamePlugin] = []

    def register(self, plugin: GamePlugin):
        self._plugins.append(plugin)

    def all(self) -> list[GamePlugin]:
        return list(self._plugins)

    def manifests(self) -> list[dict[str, object]]:
        return [dict(getattr(plugin, "manifest", {})) for plugin in self._plugins]

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> GamePlugin | None:
        for plugin in self._plugins:
            if plugin.detect(raw_data, metrics):
                return plugin
        return None

    def get(self, plugin_id: str) -> GamePlugin | None:
        for plugin in self._plugins:
            if plugin.id == plugin_id:
                return plugin
        return None


def build_default_registry(
    enabled_plugin_ids: list[str] | None = None,
    config=None,
) -> PluginRegistry:
    registry = PluginRegistry()
    enabled = set(enabled_plugin_ids or [])
    for plugin in discover_plugins(config=config):
        if enabled and plugin.id not in enabled:
            continue
        registry.register(plugin)
    return registry


def discover_plugins(config=None) -> list[GamePlugin]:
    plugins: list[GamePlugin] = []
    package_path = list(getattr(game_plugins_pkg, "__path__", []))
    for module_info in pkgutil.iter_modules(package_path):
        if module_info.name in {"base", "registry"}:
            continue
        if module_info.ispkg:
            module = importlib.import_module(f"src.game_plugins.{module_info.name}")
        else:
            if not module_info.name.endswith("_plugin"):
                continue
            module = importlib.import_module(f"src.game_plugins.{module_info.name}")
        plugin = _instantiate_plugin_from_module(module, config=config)
        if plugin is not None:
            plugins.append(plugin)
    plugins.sort(key=lambda item: str(item.manifest.get("id", item.id)))
    return plugins


def _instantiate_plugin_from_module(module, config=None) -> GamePlugin | None:
    plugin_class = getattr(module, "PLUGIN_CLASS", None)
    if plugin_class is not None:
        return _try_construct(plugin_class, config)
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        plugin_id = getattr(obj, "id", None)
        manifest = getattr(obj, "manifest", None)
        if plugin_id and isinstance(manifest, dict):
            return _try_construct(obj, config)
    return None


def _try_construct(cls, config=None):
    """Try constructing with config first, fall back to no-arg."""
    try:
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.keys())
        if config is not None and "config" in params:
            return cls(config=config)
    except (ValueError, TypeError):
        pass
    return cls()
