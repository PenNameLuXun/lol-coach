from unittest.mock import patch, MagicMock
from src.lol_client import LolClient, _format

FAKE_DATA = {
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
    "allPlayers": [
        {
            "summonerName": "TestPlayer",
            "championName": "Jinx",
            "team": "ORDER",
            "items": [
                {"displayName": "Kraken Slayer"},
                {"displayName": "Runaan's Hurricane"},
            ],
        }
    ],
    "gameData": {"gameTime": 725},
    "events": {"Events": [
        {"EventName": "DragonKill"},
        {"EventName": "ChampionKill"},
    ]},
}


def test_format_returns_string():
    result = _format(FAKE_DATA)
    assert isinstance(result, str)
    assert "Jinx" in result
    assert "12" in result  # level
    assert "1350" in result  # gold
    assert "12:05" in result  # 725s = 12:05


def test_format_includes_items():
    result = _format(FAKE_DATA)
    assert "Kraken" in result


def test_format_includes_recent_events():
    result = _format(FAKE_DATA)
    assert "击杀" in result


def test_get_game_summary_returns_none_when_not_in_game():
    with patch("src.lol_client.urllib3"):
        import requests
        with patch("requests.get", side_effect=Exception("connection refused")):
            client = LolClient()
            result = client.get_game_summary()
            assert result is None


def test_get_game_summary_returns_string_when_in_game():
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_DATA
    with patch("requests.get", return_value=mock_resp):
        client = LolClient()
        result = client.get_game_summary()
        assert result is not None
        assert "Jinx" in result
