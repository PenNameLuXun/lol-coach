from main import _build_debug_fake_lol_context, _build_debug_fake_tft_context
from src.config import Config
from src.rule_engine import RuleEngine


def test_build_debug_fake_lol_context(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "decision:\n"
        "  plugins:\n"
        "    enabled: [lol]\n",
        encoding="utf-8",
    )
    config = Config(str(path))
    engine = RuleEngine(enabled_plugin_ids=["lol"], config=config)

    context = _build_debug_fake_lol_context(engine)

    assert context is not None
    assert context.plugin.id == "lol"
    assert context.state.game_type == "lol"
    assert context.state.raw_data["activePlayer"]["summonerName"] == "DebugPlayer"


def test_build_debug_fake_tft_context(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "decision:\n"
        "  plugins:\n"
        "    enabled: [tft]\n",
        encoding="utf-8",
    )
    config = Config(str(path))
    engine = RuleEngine(enabled_plugin_ids=["tft"], config=config)

    context = _build_debug_fake_tft_context(engine)

    assert context is not None
    assert context.plugin.id == "tft"
    assert context.state.game_type == "tft"
    assert context.state.raw_data["_overwolf"]["me"]["name"] == "DebugTFTPlayer"
