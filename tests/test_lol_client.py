from unittest.mock import patch, MagicMock
from src.lol_client import LolClient, _format_lol, _format_tft, _is_tft

# ── LOL test data ─────────────────────────────────────────────────────────────

LOL_DATA = {
    "activePlayer": {
        "summonerName": "TestPlayer",
        "level": 12,
        "currentGold": 1350,
        "championStats": {
            "currentHealth": 800,
            "maxHealth": 1200,
            "resourceValue": 300,
            "resourceMax": 600,
        },
    },
    "allPlayers": [{
        "summonerName": "TestPlayer",
        "championName": "Jinx",
        "team": "ORDER",
        "items": [
            {"displayName": "Kraken Slayer"},
            {"displayName": "Runaan's Hurricane"},
        ],
    }],
    "gameData": {"gameTime": 725, "gameMode": "CLASSIC"},
    "events": {"Events": [
        {"EventName": "DragonKill"},
        {"EventName": "ChampionKill"},
    ]},
}

# ── TFT test data ─────────────────────────────────────────────────────────────

TFT_DATA = {
    "activePlayer": {
        "summonerName": "TestPlayer",
        "level": 6,
        "currentGold": 4,
    },
    "allPlayers": [
        {
            "summonerName": "TestPlayer",
            "championName": "TFT_Jinx",
            "championStats": {"currentHealth": 72},
            "items": [],
        },
        {
            "summonerName": "TestPlayer",
            "championName": "TFT_Garen",
            "championStats": {"currentHealth": 72},
            "items": [],
        },
    ],
    "gameData": {"gameTime": 480, "gameMode": "TFT"},
    "events": {"Events": [
        {"EventName": "TFT_PlayerDied"},
    ]},
}


# ── _is_tft ───────────────────────────────────────────────────────────────────

def test_is_tft_detects_gamemode_field():
    assert _is_tft(TFT_DATA) is True


def test_is_tft_detects_tft_prefix():
    data = dict(TFT_DATA)
    data["gameData"] = {"gameTime": 0, "gameMode": "CLASSIC"}
    assert _is_tft(data) is True


def test_is_tft_returns_false_for_lol():
    assert _is_tft(LOL_DATA) is False


# ── LOL formatter ─────────────────────────────────────────────────────────────

def test_format_lol_returns_string():
    result = _format_lol(LOL_DATA)
    assert "Jinx" in result
    assert "12" in result
    assert "1350" in result
    assert "12:05" in result


def test_format_lol_includes_items():
    assert "Kraken" in _format_lol(LOL_DATA)


def test_format_lol_includes_events():
    assert "击杀" in _format_lol(LOL_DATA)


# ── TFT formatter ─────────────────────────────────────────────────────────────

def test_format_tft_returns_string():
    result = _format_tft(TFT_DATA)
    assert "云顶之弈" in result
    assert "8:00" in result  # 480s
    assert "等级6" in result


def test_format_tft_includes_units():
    result = _format_tft(TFT_DATA)
    assert "Jinx" in result
    assert "Garen" in result


def test_format_tft_strips_tft_prefix():
    result = _format_tft(TFT_DATA)
    assert "TFT_" not in result


def test_format_tft_includes_events():
    result = _format_tft(TFT_DATA)
    assert "淘汰" in result


# ── LolClient ─────────────────────────────────────────────────────────────────

def test_get_game_summary_returns_none_when_not_in_game():
    with patch("requests.get", side_effect=Exception("connection refused")):
        assert LolClient().get_game_summary() is None


def test_get_game_summary_auto_detects_lol():
    mock_resp = MagicMock()
    mock_resp.json.return_value = LOL_DATA
    with patch("requests.get", return_value=mock_resp):
        result = LolClient().get_game_summary()
        assert result is not None
        assert "云顶之弈" not in result
        assert "Jinx" in result


def test_get_game_summary_auto_detects_tft():
    mock_resp = MagicMock()
    mock_resp.json.return_value = TFT_DATA
    with patch("requests.get", return_value=mock_resp):
        result = LolClient().get_game_summary()
        assert result is not None
        assert "云顶之弈" in result
