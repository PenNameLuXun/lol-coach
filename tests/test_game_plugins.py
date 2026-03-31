from src.game_plugins import build_default_registry
from src.game_plugins.registry import discover_plugins
from tests.test_lol_client import LOL_DATA, TFT_DATA


def test_registry_detects_lol_plugin():
    registry = build_default_registry()
    plugin = registry.detect(LOL_DATA, {"game_type": "lol"})
    assert plugin is not None
    assert plugin.id == "lol"


def test_registry_detects_tft_plugin():
    registry = build_default_registry()
    plugin = registry.detect(TFT_DATA, {"game_type": "tft"})
    assert plugin is not None
    assert plugin.id == "tft"


def test_discover_plugins_loads_manifests():
    plugins = discover_plugins()
    plugin_ids = {plugin.id for plugin in plugins}
    assert {"lol", "tft"}.issubset(plugin_ids)
    assert all(isinstance(plugin.manifest, dict) for plugin in plugins)


def test_registry_can_filter_enabled_plugins():
    registry = build_default_registry(enabled_plugin_ids=["lol"])
    manifests = registry.manifests()
    assert len(manifests) == 1
    assert manifests[0]["id"] == "lol"
