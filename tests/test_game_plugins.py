from src.game_plugins import build_default_registry
from src.config import Config
from src.game_plugins.registry import discover_plugins
from src.game_plugins.dialogue import source as dialogue_source_module
from src.game_plugins.tft.plugin import TftPlugin
from src.qa_channel import QaChannel, build_qa_prompt
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
    assert {"lol", "tft", "dialogue"}.issubset(plugin_ids)
    assert all(isinstance(plugin.manifest, dict) for plugin in plugins)


def test_registry_can_filter_enabled_plugins():
    registry = build_default_registry(enabled_plugin_ids=["lol"])
    manifests = registry.manifests()
    assert len(manifests) == 1
    assert manifests[0]["id"] == "lol"


def test_lol_plugin_builds_ai_payload():
    registry = build_default_registry(enabled_plugin_ids=["lol"])
    plugin = registry.get("lol")
    assert plugin is not None
    state = plugin.extract_state(LOL_DATA, {})

    payload = plugin.build_ai_payload(state, detail="minimal", address_by="champion")

    assert "时间12:05" in payload.game_summary
    assert payload.address == "Jinx"
    assert payload.metrics["gold"] == 1350


def test_tft_plugin_builds_ai_payload():
    registry = build_default_registry(enabled_plugin_ids=["tft"])
    plugin = registry.get("tft")
    assert plugin is not None
    state = plugin.extract_state(TFT_DATA, {})

    payload = plugin.build_ai_payload(state, detail="minimal", address_by="summoner")

    assert "云顶之弈" in payload.game_summary
    assert payload.address == "TestPlayer"
    assert payload.metrics["game_type"] == "tft"


def test_lol_plugin_builds_rule_hint():
    registry = build_default_registry(enabled_plugin_ids=["lol"])
    plugin = registry.get("lol")
    assert plugin is not None
    state = plugin.extract_state(LOL_DATA, {"hp_pct": 20, "gold": 1800})
    rule = plugin.evaluate_rules(state)[0]

    hint = plugin.build_rule_hint(rule, state)

    assert "规则观察" in hint
    assert rule.message in hint


def test_lol_plugin_builds_decision_prompt():
    registry = build_default_registry(enabled_plugin_ids=["lol"])
    plugin = registry.get("lol")
    assert plugin is not None
    state = plugin.extract_state(LOL_DATA, {})

    prompt = plugin.build_decision_prompt(
        state,
        system_prompt="你是教练",
        bridge_facts={"confidence": "high", "scene": "river", "player_risk": "medium"},
        snapshots=[],
        rule_hint="敌方减员，可转资源",
        detail="minimal",
        address_by="champion",
    )

    assert "你是教练" in prompt
    assert "当前游戏摘要" in prompt
    assert "规则引擎提示：敌方减员，可转资源" in prompt
    assert "视觉核验置信度：high" in prompt


def test_tft_plugin_builds_game_specific_prompts():
    registry = build_default_registry(enabled_plugin_ids=["tft"])
    plugin = registry.get("tft")
    assert plugin is not None
    state = plugin.extract_state(TFT_DATA, {})

    vision_prompt = plugin.build_vision_prompt(state, detail="minimal")
    decision_prompt = plugin.build_decision_prompt(
        state,
        system_prompt="你是云顶教练",
        bridge_facts={"confidence": "high", "board_strength": "stable", "upgrade_window": "roll_now"},
        snapshots=[],
        rule_hint="血量危险，准备搜牌保血",
        detail="minimal",
        address_by="summoner",
    )

    assert "云顶之弈视觉核验模块" in vision_prompt
    assert "board_strength:" in vision_prompt
    assert "当前云顶摘要" in decision_prompt
    assert "不要猜测具体羁绊" in decision_prompt


def test_tft_plugin_supports_overwolf_only_snapshot():
    plugin = TftPlugin()
    raw_data = {
        "_game_type": "tft",
        "_source": "overwolf",
        "_overwolf": {
            "me": {"name": "TestPlayer"},
            "hp": 72,
            "gold": 34,
            "level": 7,
            "alive_players": 5,
            "round": "4-2",
            "mode": "TFT",
            "game_time": "18:20",
            "game_time_seconds": 1100,
            "shop": [{"name": "安妮", "cost": 2}],
            "traits": [{"name": "法师", "tier_current": 3}],
        },
    }

    assert plugin.detect(raw_data, {}) is True
    state = plugin.extract_state(raw_data, {})
    payload = plugin.build_ai_payload(state, detail="normal", address_by="summoner")

    assert state.derived["data_source"] == "overwolf"
    assert "Overwolf" in payload.game_summary
    assert "安妮(2)" in payload.game_summary
    assert payload.address == "TestPlayer"


def test_dialogue_plugin_builds_reply_prompt(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    input_path = tmp_path / "dialogue_input.txt"
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: file\n"
            f"    text_file: {input_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    clear_after_read: false\n"
        ),
        encoding="utf-8",
    )
    input_path.write_text("你好，帮我测试一下语音回复。", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    registry = build_default_registry(enabled_plugin_ids=["dialogue"])
    plugin = registry.get("dialogue")
    assert plugin is not None
    raw_data = plugin.fetch_live_data()
    assert raw_data is not None
    state = plugin.extract_state(raw_data, {})
    assert plugin.wants_visual_context(state) is False

    prompt = plugin.build_decision_prompt(
        state,
        system_prompt="你是测试助手",
        bridge_facts=None,
        snapshots=[],
        detail="normal",
        address_by="summoner",
    )

    assert "语音对话测试" in prompt
    assert "你好，帮我测试一下语音回复。" in prompt
    assert "测试玩家" in prompt


def test_dialogue_source_reads_lines_in_loop_without_mutating_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    input_path = tmp_path / "dialogue_input.txt"
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: file\n"
            f"    text_file: {input_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    clear_after_read: false\n"
        ),
        encoding="utf-8",
    )
    input_path.write_text("第一行\n\n第二行\n第三行\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    registry = build_default_registry(enabled_plugin_ids=["dialogue"])
    plugin = registry.get("dialogue")
    assert plugin is not None

    texts = []
    for _ in range(4):
        raw_data = plugin.fetch_live_data()
        assert raw_data is not None
        texts.append(raw_data["dialogue"]["text"])

    assert texts == ["第一行", "第二行", "第三行", "第一行"]
    assert input_path.read_text(encoding="utf-8") == "第一行\n\n第二行\n第三行\n"


def test_dialogue_source_reads_microphone_transcript_incrementally(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    transcript_path = tmp_path / "dialogue_mic.txt"
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: microphone\n"
            f"    transcript_file: {transcript_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    recognition_language: zh-CN\n"
            "    auto_start_listener: true\n"
        ),
        encoding="utf-8",
    )
    transcript_path.write_text("旧句子\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        dialogue_source_module.WindowsMicrophoneListener,
        "ensure_running",
        lambda self, transcript_path, culture="zh-CN": True,
    )

    source = dialogue_source_module.DialogueSource()

    assert source.is_available() is True
    assert source.fetch_live_data() is None

    transcript_path.write_text("旧句子\n第一句\n第二句\n", encoding="utf-8")

    first = source.fetch_live_data()
    second = source.fetch_live_data()
    third = source.fetch_live_data()

    assert first is not None
    assert second is not None
    assert third is None
    assert first["dialogue"]["text"] == "第一句"
    assert second["dialogue"]["text"] == "第二句"
    assert first["dialogue"]["line_mode"] == "append_only"
    assert second["dialogue"]["source"] == "microphone"


def test_dialogue_source_resets_append_index_after_transcript_trim(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    transcript_path = tmp_path / "dialogue_mic.txt"
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: microphone\n"
            f"    transcript_file: {transcript_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    recognition_language: zh-CN\n"
            "    auto_start_listener: true\n"
        ),
        encoding="utf-8",
    )
    transcript_path.write_text("历史句\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        dialogue_source_module.WindowsMicrophoneListener,
        "ensure_running",
        lambda self, transcript_path, culture="zh-CN": True,
    )

    source = dialogue_source_module.DialogueSource()
    assert source.fetch_live_data() is None

    transcript_path.write_text("历史句\n第一句\n第二句\n第三句\n", encoding="utf-8")
    assert source.fetch_live_data()["dialogue"]["text"] == "第一句"
    assert source.fetch_live_data()["dialogue"]["text"] == "第二句"
    assert source.fetch_live_data()["dialogue"]["text"] == "第三句"

    transcript_path.write_text("保留句\n新句\n", encoding="utf-8")

    first_after_trim = source.fetch_live_data()
    second_after_trim = source.fetch_live_data()

    assert first_after_trim is not None
    assert second_after_trim is not None
    assert first_after_trim["dialogue"]["text"] == "保留句"
    assert second_after_trim["dialogue"]["text"] == "新句"


def test_dialogue_source_trims_large_transcript_from_reader_side(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    transcript_path = tmp_path / "dialogue_mic.txt"
    oversized_line = "超长语音片段" * 120000
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: microphone\n"
            f"    transcript_file: {transcript_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    recognition_language: zh-CN\n"
            "    auto_start_listener: true\n"
            "    max_transcript_mb: 1\n"
        ),
        encoding="utf-8",
    )
    transcript_path.write_text("历史句\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        dialogue_source_module.WindowsMicrophoneListener,
        "ensure_running",
        lambda self, transcript_path, culture="zh-CN": True,
    )

    source = dialogue_source_module.DialogueSource()
    assert source.fetch_live_data() is None
    transcript_path.write_text(f"历史句\n{oversized_line}\n最后一句\n", encoding="utf-8")
    payload = source.fetch_live_data()

    assert payload is not None
    assert payload["dialogue"]["text"]
    assert transcript_path.stat().st_size <= 1024 * 1024


def test_dialogue_plugin_rules_echo_input(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    input_path = tmp_path / "dialogue_input.txt"
    config_path.write_text(
        (
            "plugin_settings:\n"
            "  dialogue:\n"
            "    source: file\n"
            f"    text_file: {input_path.as_posix()}\n"
            "    speaker: 测试玩家\n"
            "    clear_after_read: false\n"
        ),
        encoding="utf-8",
    )
    input_path.write_text("规则模式测试", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    registry = build_default_registry(enabled_plugin_ids=["dialogue"])
    plugin = registry.get("dialogue")
    assert plugin is not None
    raw_data = plugin.fetch_live_data()
    assert raw_data is not None
    state = plugin.extract_state(raw_data, {})

    rules = plugin.evaluate_rules(state)

    assert len(rules) == 1
    assert rules[0].message == "规则模式测试"


def test_qa_channel_reads_question_and_builds_prompt(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    input_path = tmp_path / "game_qa_input.txt"
    transcript_path = tmp_path / "game_qa_mic.txt"
    config_path.write_text(
        (
            "qa:\n"
            "  enabled: true\n"
            "  source: file\n"
            f"  text_file: {input_path.as_posix()}\n"
            f"  transcript_file: {transcript_path.as_posix()}\n"
            "  speaker: 玩家A\n"
        ),
        encoding="utf-8",
    )
    input_path.write_text("历史问题\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    channel = QaChannel(config_path=str(config_path))
    cfg = Config(str(config_path))
    assert channel.poll_question() is None

    input_path.write_text("历史问题\n我玩剑圣怎么对线蛮王？\n", encoding="utf-8")
    question = channel.poll_question()

    assert cfg.qa_enabled is True
    assert question is not None
    assert question.text == "我玩剑圣怎么对线蛮王？"
    assert "我玩剑圣怎么对线蛮王？" in transcript_path.read_text(encoding="utf-8")

    plugin = build_default_registry(enabled_plugin_ids=["lol"]).get("lol")
    assert plugin is not None
    active_context = type("Ctx", (), {"plugin": plugin, "state": plugin.extract_state(LOL_DATA, {})})()
    prompt = build_qa_prompt(
        question=question,
        system_prompt="你是游戏问答助手",
        active_context=active_context,
        snapshots=[],
        rule_advice=None,
        detail="normal",
        address_by="summoner",
    )

    assert "回答玩家的游戏问题" in prompt
    assert "我玩剑圣怎么对线蛮王？" in prompt
    assert "玩家A" in prompt
    assert "当前对局摘要" in prompt
