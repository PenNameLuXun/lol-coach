from src.rule_engine import RuleEngine
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
    mocker.patch.object(plugin, "fetch_live_data", return_value=LOL_DATA)
    context = engine.discover_active_context()
    assert context is not None
    assert context.plugin.id == "lol"
    assert context.state.plugin_id == "lol"
