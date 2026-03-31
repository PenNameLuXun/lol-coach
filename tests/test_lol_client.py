from unittest.mock import patch, MagicMock
from src.game_plugins.league_shared.live_client import (
    LeagueLiveClient,
    _format_lol,
    _format_tft,
    _is_tft,
    extract_key_metrics,
    get_player_address_from_data,
    summarize_game_data,
)

# ── shared LOL test data ──────────────────────────────────────────────────────

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
        "fullRunes": {"keystone": {"displayName": "Conqueror"}},
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
            "scores": {"kills": 3, "deaths": 1, "assists": 5, "creepScore": 120, "wardScore": 22},
            "summonerSpells": {
                "summonerSpellOne": {"displayName": "Flash"},
                "summonerSpellTwo": {"displayName": "Heal"},
            },
            "isDead": False,
            "respawnTimer": 0.0,
        },
        {
            "summonerName": "Ally1",
            "championName": "Thresh",
            "team": "ORDER",
            "scores": {"kills": 1, "deaths": 2, "assists": 8, "creepScore": 20, "wardScore": 40},
            "isDead": False,
            "respawnTimer": 0.0,
            "items": [],
        },
        {
            "summonerName": "Enemy1",
            "championName": "Zed",
            "team": "CHAOS",
            "scores": {"kills": 5, "deaths": 1, "assists": 2, "creepScore": 150, "wardScore": 15},
            "isDead": True,
            "respawnTimer": 12.0,
            "items": [],
        },
    ],
    "gameData": {"gameTime": 725, "gameMode": "CLASSIC"},
    "events": {"Events": [
        {"EventName": "DragonKill", "DragonType": "Fire"},
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
        {
            "summonerName": "OtherPlayer1",
            "championName": "TFT_Lux",
            "championStats": {"currentHealth": 55},
            "items": [],
        },
        {
            "summonerName": "OtherPlayer2",
            "championName": "TFT_Zed",
            "championStats": {"currentHealth": 20},
            "items": [],
        },
    ],
    "gameData": {"gameTime": 480, "gameMode": "TFT"},
    "events": {"Events": [
        {"EventName": "TFT_PlayerDied"},
        {"EventName": "TFT_Augment"},
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

def test_format_lol_minimal():
    result = _format_lol(LOL_DATA, "minimal")
    assert "Jinx" in result
    assert "12:05" in result
    assert "KDA" not in result
    assert "装备" not in result


def test_format_lol_normal_includes_items_and_events():
    result = _format_lol(LOL_DATA, "normal")
    assert "Kraken" in result
    assert "击杀" in result
    assert "KDA" not in result


def test_format_lol_full_includes_kda_and_teams():
    result = _format_lol(LOL_DATA, "full")
    assert "KDA3/1/5" in result
    assert "补刀120" in result
    assert "Thresh" in result   # ally
    assert "Zed" in result      # enemy
    assert "Conqueror" in result  # keystone
    assert "Flash" in result


def test_format_lol_full_includes_dragon_type():
    result = _format_lol(LOL_DATA, "full")
    assert "Fire" in result


# ── TFT formatter ─────────────────────────────────────────────────────────────

def test_format_tft_minimal():
    result = _format_tft(TFT_DATA, "minimal")
    assert "云顶之弈" in result
    assert "等级6" in result
    assert "棋子" not in result
    assert "金币4" in result       # gold shown in all detail levels
    assert "利息0" in result       # interest shown in all detail levels
    assert "存活" in result        # alive player count


def test_format_tft_normal_includes_units_and_events():
    result = _format_tft(TFT_DATA, "normal")
    assert "Jinx" in result
    assert "Garen" in result
    assert "淘汰" in result
    assert "已选强化" in result    # augment tracking
    assert "其他玩家" not in result


def test_format_tft_full_includes_standings_and_gold():
    result = _format_tft(TFT_DATA, "full")
    assert "金币4" in result
    assert "其他玩家生命" in result
    assert "OtherPlayer1" in result
    assert "OtherPlayer2" in result


def test_format_tft_strips_tft_prefix():
    result = _format_tft(TFT_DATA, "normal")
    assert "TFT_" not in result


def test_format_tft_full_standings_sorted_by_hp():
    result = _format_tft(TFT_DATA, "full")
    # OtherPlayer1 (55 HP) should appear before OtherPlayer2 (20 HP)
    assert result.index("OtherPlayer1") < result.index("OtherPlayer2")


# ── LolClient ─────────────────────────────────────────────────────────────────

def test_get_game_summary_returns_none_when_not_in_game():
    with patch("requests.get", side_effect=Exception("connection refused")):
        assert LeagueLiveClient().get_game_summary() is None


def test_get_game_summary_auto_detects_lol():
    mock_resp = MagicMock()
    mock_resp.json.return_value = LOL_DATA
    with patch("requests.get", return_value=mock_resp):
        result = LeagueLiveClient().get_game_summary()
        assert result is not None
        assert "云顶之弈" not in result
        assert "Jinx" in result


def test_get_game_summary_auto_detects_tft():
    mock_resp = MagicMock()
    mock_resp.json.return_value = TFT_DATA
    with patch("requests.get", return_value=mock_resp):
        result = LeagueLiveClient().get_game_summary()
        assert result is not None
        assert "云顶之弈" in result


def test_extract_key_metrics_returns_normalized_fields():
    metrics = extract_key_metrics(LOL_DATA)
    assert metrics["game_time"] == "12:05"
    assert metrics["gold"] == 1350
    assert metrics["hp_pct"] == 66
    assert metrics["kda"] == "3/1/5"
    assert metrics["event_signature"] == "DragonKill|ChampionKill"


def test_get_player_address_from_data_uses_champion_name():
    assert get_player_address_from_data(LOL_DATA, "champion") == "Jinx"


def test_summarize_game_data_uses_formatter():
    result = summarize_game_data(LOL_DATA, "minimal")
    assert "时间12:05" in result
