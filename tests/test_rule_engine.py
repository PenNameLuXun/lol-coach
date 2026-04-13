from src.rule_engine import EngineState, RuleEngine
from tests.test_lol_client import LOL_DATA, TFT_DATA


def test_rule_engine_returns_lol_low_hp_rule():
    engine = RuleEngine()
    data = {
        **LOL_DATA,
        "activePlayer": {
            **LOL_DATA["activePlayer"],
            "currentGold": 1800,
            "championStats": {
                **LOL_DATA["activePlayer"]["championStats"],
                "currentHealth": 150,
                "maxHealth": 1200,
            },
        },
    }
    metrics = {
        "hp_pct": 12,
        "mana_pct": 30,
        "gold": 1800,
        "event_signature": "none",
        "is_dead": "false",
    }
    advice = engine.evaluate(data, metrics)
    assert advice is not None
    assert advice.game_type == "lol"
    assert advice.plugin_id == "lol"
    assert "回城" in advice.text


def test_rule_engine_returns_tft_roll_rule():
    engine = RuleEngine()
    data = {
        **TFT_DATA,
        "activePlayer": {
            **TFT_DATA["activePlayer"],
            "currentGold": 32,
        },
        "allPlayers": [
            {
                **TFT_DATA["allPlayers"][0],
                "championStats": {"currentHealth": 18},
            },
            *TFT_DATA["allPlayers"][1:],
        ],
    }
    metrics = {
        "game_type": "tft",
        "gold": 32,
    }
    advice = engine.evaluate(data, metrics)
    assert advice is not None
    assert advice.game_type == "tft"
    assert advice.plugin_id == "tft"
    assert "搜牌" in advice.text


def test_rule_engine_discovers_active_context(mocker):
    engine = RuleEngine()
    plugin = engine.registry.get("lol")
    assert plugin is not None
    mocker.patch.object(plugin, "is_available", return_value=True)
    mocker.patch.object(plugin, "fetch_live_data", return_value=LOL_DATA)
    context = engine.discover_active_context()
    assert context is not None
    assert context.plugin.id == "lol"
    assert context.state.plugin_id == "lol"


def test_rule_engine_binds_plugin_after_discovery(mocker):
    engine = RuleEngine()
    lol_plugin = engine.registry.get("lol")
    tft_plugin = engine.registry.get("tft")
    assert lol_plugin is not None
    assert tft_plugin is not None
    mocker.patch.object(lol_plugin, "is_available", return_value=True)
    fetch_mock = mocker.patch.object(lol_plugin, "fetch_live_data", return_value=LOL_DATA)
    detect_mock = mocker.patch.object(lol_plugin, "detect", return_value=True)
    tft_available_mock = mocker.patch.object(tft_plugin, "is_available", return_value=False)

    context = engine.discover_active_context()
    assert context is not None
    assert context.plugin.id == "lol"
    assert engine.state == EngineState.BOUND
    assert engine.bound_plugin_id == "lol"
    fetch_mock.assert_called_once()
    detect_mock.assert_called_once()


def test_rule_engine_invalidates_binding_when_bound_plugin_fails(mocker):
    engine = RuleEngine()
    lol_plugin = engine.registry.get("lol")
    tft_plugin = engine.registry.get("tft")
    assert lol_plugin is not None
    assert tft_plugin is not None
    engine.bind_plugin("lol")
    mocker.patch.object(lol_plugin, "is_available", return_value=False)
    mocker.patch.object(tft_plugin, "is_available", return_value=False)

    context = engine.discover_active_context()
    assert context is None
    assert engine.state == EngineState.DISCOVERING
    assert engine.bound_plugin_id is None
