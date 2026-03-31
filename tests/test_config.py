import os
import time
import tempfile
import pytest
import yaml
from src.config import Config

MINIMAL_CONFIG = {
    "decision": {
        "mode": "hybrid",
        "plugins": {"enabled": ["lol"]},
        "rules": {"hybrid_priority_threshold": 88},
    },
    "ai": {
        "provider": "claude",
        "system_prompt": "test prompt",
        "decision_memory_size": 4,
        "analysis_trigger": {"force_after_seconds": 30, "hp_drop_pct": 18},
        "claude": {"api_key": "k1", "model": "claude-opus-4-6", "max_tokens": 200, "temperature": 0.7},
        "openai": {"api_key": "k2", "model": "gpt-4o", "max_tokens": 200, "temperature": 0.7},
        "gemini": {"api_key": "k3", "model": "gemini-1.5-pro", "max_tokens": 200, "temperature": 0.7},
        "vision_bridge": {"provider": "openai", "model": "gpt-4.1-mini"},
    },
    "tts": {
        "backend": "windows",
        "interrupt": True,
        "windows": {"rate": 180, "volume": 1.0},
        "edge": {"voice": "zh-CN-XiaoxiaoNeural"},
        "openai": {"api_key": "k4", "voice": "alloy", "model": "tts-1"},
    },
    "capture": {"interval": 5, "hotkey": "ctrl+shift+a", "region": "fullscreen", "jpeg_quality": 85},
    "overlay": {"enabled": True, "x": 100, "y": 100, "fade_after": 8, "toggle_hotkey": "ctrl+shift+h"},
    "app": {"start_minimized": True},
    "plugin_settings": {
        "lol": {"detail": "full", "address_by": "champion", "require_game": True},
        "dialogue": {"source": "file", "text_file": "dialogue_input.txt", "speaker": "玩家", "clear_after_read": True},
    },
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(MINIMAL_CONFIG))
    return str(path)


def test_load_returns_correct_provider(config_file):
    cfg = Config(config_file)
    assert cfg.ai_provider == "claude"


def test_load_returns_api_key(config_file):
    cfg = Config(config_file)
    assert cfg.ai_config("claude")["api_key"] == "k1"


def test_load_tts_backend(config_file):
    cfg = Config(config_file)
    assert cfg.tts_backend == "windows"


def test_load_capture_interval(config_file):
    cfg = Config(config_file)
    assert cfg.capture_interval == 5


def test_save_roundtrip(config_file):
    cfg = Config(config_file)
    cfg.set("capture.interval", 10)
    cfg2 = Config(config_file)
    assert cfg2.capture_interval == 10


def test_hot_reload_calls_callback(config_file):
    cfg = Config(config_file)
    called = []
    cfg.on_reload(lambda: called.append(True))
    cfg._start_watcher()

    # Modify the file
    time.sleep(0.05)
    with open(config_file, "r") as f:
        data = yaml.safe_load(f)
    data["capture"]["interval"] = 99
    with open(config_file, "w") as f:
        yaml.dump(data, f)

    time.sleep(1.5)  # watcher polls every 1s
    cfg._stop_watcher()
    assert len(called) >= 1


def test_get_nested_key(config_file):
    cfg = Config(config_file)
    assert cfg.get("overlay.x") == 100


def test_system_prompt(config_file):
    cfg = Config(config_file)
    assert cfg.system_prompt == "test prompt"


def test_decision_memory_size(config_file):
    cfg = Config(config_file)
    assert cfg.decision_memory_size == 4


def test_vision_bridge_defaults_enabled_when_present(config_file):
    cfg = Config(config_file)
    assert cfg.vision_bridge == {"provider": "openai", "model": "gpt-4.1-mini"}


def test_analysis_trigger_config(config_file):
    cfg = Config(config_file)
    assert cfg.analysis_trigger["force_after_seconds"] == 30


def test_vision_bridge_provider_config_merges_override(config_file):
    cfg = Config(config_file)
    provider, bridge_cfg = cfg.vision_bridge_provider_config()
    assert provider == "openai"
    assert bridge_cfg["model"] == "gpt-4.1-mini"
    assert bridge_cfg["api_key"] == "k2"


def test_decision_mode_and_rules_config(config_file):
    cfg = Config(config_file)
    assert cfg.decision_mode == "hybrid"
    assert cfg.rules_config["hybrid_priority_threshold"] == 88
    assert cfg.enabled_plugins == ["lol"]


def test_plugin_settings_helpers(config_file):
    cfg = Config(config_file)
    assert cfg.plugin_settings("dialogue")["source"] == "file"
    assert cfg.plugin_detail("lol") == "full"
    assert cfg.plugin_address_by("lol") == "champion"
    assert cfg.plugin_require_game("lol") is True


def test_update_many_saves_once_with_plugin_settings(config_file):
    cfg = Config(config_file)
    cfg.update_many(
        {
            "plugin_settings.dialogue.source": "microphone",
            "plugin_settings.dialogue.speaker": "测试员",
        }
    )
    cfg2 = Config(config_file)
    assert cfg2.plugin_setting("dialogue", "source") == "microphone"
    assert cfg2.plugin_setting("dialogue", "speaker") == "测试员"
