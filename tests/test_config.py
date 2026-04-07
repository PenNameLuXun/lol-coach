import os
import time
import tempfile
import pytest
import yaml
from src.config import Config
from main import _resolve_tts_rate_override

MINIMAL_CONFIG = {
    "decision": {
        "mode": "hybrid",
        "plugins": {"enabled": ["lol"]},
        "rules": {"hybrid_priority_threshold": 88},
    },
    "scheduler": {"interval": 4},
    "overwolf": {"enabled": False, "host": "127.0.0.1", "port": 7799, "stale_after_seconds": 5},
    "ai": {
        "provider": "claude",
        "decision_memory_size": 4,
        "claude": {"api_key": "k1", "model": "claude-opus-4-6", "max_tokens": 200, "temperature": 0.7},
        "openai": {"api_key": "k2", "model": "gpt-4o", "max_tokens": 200, "temperature": 0.7},
        "gemini": {"api_key": "k3", "model": "gemini-1.5-pro", "max_tokens": 200, "temperature": 0.7},
        "vision_bridge": {"provider": "openai", "model": "gpt-4.1-mini"},
    },
    "tts": {
        "backend": "windows",
        "playback_mode": "continue",
        "windows": {"rate": 180, "volume": 1.0},
        "edge": {"voice": "zh-CN-XiaoxiaoNeural"},
        "openai": {"api_key": "k4", "voice": "alloy", "model": "tts-1"},
    },
    "capture": {"interval": 5, "hotkey": "ctrl+shift+a", "region": "fullscreen", "jpeg_quality": 85},
    "overlay": {"enabled": True, "x": 100, "y": 100, "fade_after": 8, "toggle_hotkey": "ctrl+shift+h"},
    "app": {"start_minimized": True},
    "plugin_settings": {
        "lol": {
            "detail": "full",
            "address_by": "champion",
            "require_game": True,
            "system_prompt": "lol prompt",
            "qa_search_sites_text": "op.gg,100\nu.gg,95",
            "trigger_force_after_seconds": 30,
            "trigger_hp_drop_pct": 18,
            "trigger_gold_delta": 300,
            "trigger_cs_delta": 6,
            "trigger_skip_stable_cycles": True,
        },
        "dialogue": {
            "source": "file",
            "text_file": "dialogue_input.txt",
            "speaker": "玩家",
            "clear_after_read": True,
            "system_prompt": "dialogue prompt",
        },
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
    assert cfg.tts_playback_mode == "continue"
    assert cfg.scheduler_interval == 4


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


def test_decision_memory_size(config_file):
    cfg = Config(config_file)
    assert cfg.decision_memory_size == 4


def test_vision_bridge_defaults_enabled_when_present(config_file):
    cfg = Config(config_file)
    assert cfg.vision_bridge == {"provider": "openai", "model": "gpt-4.1-mini"}


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
    assert cfg.plugin_system_prompt("lol") == "lol prompt"
    assert cfg.plugin_analysis_trigger("lol")["force_after_seconds"] == 30
    assert cfg.overwolf["port"] == 7799


def test_qa_web_search_settings_and_site_merge(config_file):
    cfg = Config(config_file)
    cfg.update_many(
        {
            "web_knowledge.always_visible": True,
            "qa.web_search_enabled": True,
            "qa.stt_backend": "funasr",
            "qa.funasr_model": "paraformer-zh",
            "qa.microphone_trigger_mode": "hold",
            "qa.microphone_hotkey": "ctrl+space",
            "qa.wakeword_enabled": True,
            "qa.wakeword_keywords_text": "小助手\n教练",
            "qa.wakeword_ack_texts_text": "你说\n在",
            "qa.web_search_engine": "duckduckgo",
            "qa.web_search_timeout_seconds": 9,
            "qa.web_search_max_results_per_site": 2,
            "qa.web_search_max_pages": 4,
            "qa.web_search_sites_text": "mobafire.com,70\nu.gg,80",
        }
    )
    cfg2 = Config(config_file)
    assert cfg2.web_knowledge_always_visible is True
    assert cfg2.qa_web_search_enabled is True
    assert cfg2.qa_stt_backend == "funasr"
    assert cfg2.qa_funasr_model == "paraformer-zh"
    assert cfg2.qa_microphone_trigger_mode == "hold"
    assert cfg2.qa_microphone_hotkey == "ctrl+space"
    assert cfg2.qa_wakeword_enabled is True
    assert cfg2.qa_wakeword_keywords == ["小助手", "教练"]
    assert cfg2.qa_wakeword_ack_texts == ["你说", "在"]
    assert cfg2.qa_web_search_engine == "duckduckgo"
    assert cfg2.qa_web_search_timeout_seconds == 9
    assert cfg2.qa_web_search_max_results_per_site == 2
    assert cfg2.qa_web_search_max_pages == 4
    assert cfg2.qa_web_search_sites("lol") == [
        {"domain": "op.gg", "priority": 100},
        {"domain": "u.gg", "priority": 95},
        {"domain": "mobafire.com", "priority": 70},
    ]


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


def test_fit_rate_does_not_slow_below_base(config_file):
    cfg = Config(config_file)
    cfg.update_many(
        {
            "scheduler.interval": 10,
            "tts.playback_mode": "fit_wait",
            "tts.windows.rate": 2,
        }
    )
    cfg2 = Config(config_file)

    class DummyEngine:
        def supports_dynamic_rate(self):
            return True

    rate = _resolve_tts_rate_override(cfg2, "windows", DummyEngine(), "短句")
    assert rate == 2
