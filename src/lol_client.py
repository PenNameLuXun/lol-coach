"""League of Legends / TFT Live Client Data API client.

Fetches real-time game state from the local API exposed by the LOL process
at https://127.0.0.1:2999 during an active game.

Auto-detects TFT vs normal LOL from the response data.
Returns None when not in game (connection refused / timeout).
"""

import urllib3
import urllib3.exceptions

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE = "https://127.0.0.1:2999/liveclientdata"


class LolClient:
    def get_game_summary(self) -> str | None:
        """Return a compact Chinese game-state string, or None if not in game."""
        try:
            import requests
            data = requests.get(f"{_BASE}/allgamedata", verify=False, timeout=1).json()
            if _is_tft(data):
                return _format_tft(data)
            return _format_lol(data)
        except Exception:
            return None


# ── Detection ─────────────────────────────────────────────────────────────────

def _is_tft(data: dict) -> bool:
    """Detect TFT by game mode field or TFT_ champion name prefix."""
    mode = data.get("gameData", {}).get("gameMode", "").upper()
    if mode == "TFT":
        return True
    players = data.get("allPlayers", [])
    if players:
        return players[0].get("championName", "").startswith("TFT_")
    return False


# ── LOL formatter ─────────────────────────────────────────────────────────────

def _format_lol(data: dict) -> str:
    active = data.get("activePlayer", {})
    stats = active.get("championStats", {})

    hp = stats.get("currentHealth", 0)
    max_hp = stats.get("maxHealth", 1)
    hp_pct = int(hp / max_hp * 100)

    mana = stats.get("resourceValue", 0)
    max_mana = stats.get("resourceMax", 1)
    mana_pct = int(mana / max_mana * 100) if max_mana else 0

    gold = int(active.get("currentGold", 0))
    level = active.get("level", 1)

    game_time = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time, 60)

    my_name = active.get("summonerName", "")
    my_champ = ""
    items: list[str] = []
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            my_champ = player.get("championName", "")
            items = [i["displayName"] for i in player.get("items", []) if i.get("displayName")]
            break

    events = data.get("events", {}).get("Events", [])
    _notable = {"DragonKill", "BaronKill", "TurretKilled", "ChampionKill", "InhibKilled", "HeraldKill"}
    _labels = {
        "DragonKill": "击杀龙", "BaronKill": "击杀大龙", "TurretKilled": "推塔",
        "ChampionKill": "击杀英雄", "InhibKilled": "推水晶", "HeraldKill": "击杀先锋",
    }
    recent = [_labels[e["EventName"]] for e in events[-8:] if e.get("EventName") in _notable]

    parts = [
        f"时间{minutes}:{seconds:02d}",
        f"英雄{my_champ}" if my_champ else "",
        f"等级{level}",
        f"血{hp_pct}%",
        f"蓝{mana_pct}%" if mana_pct else "",
        f"金币{gold}",
        f"装备{'|'.join(items[:4])}" if items else "无装备",
    ]
    if recent:
        parts.append(f"近期{'|'.join(recent[-3:])}")
    return "，".join(p for p in parts if p)


# ── TFT formatter ─────────────────────────────────────────────────────────────

def _format_tft(data: dict) -> str:
    active = data.get("activePlayer", {})
    level = active.get("level", 1)

    game_time = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time, 60)

    my_name = active.get("summonerName", "")

    # Find my player entry for HP
    my_hp = None
    units: list[str] = []
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            # TFT HP is stored in championStats.currentHealth (0-100 life points)
            stats = player.get("championStats", {})
            hp = stats.get("currentHealth")
            if hp is not None:
                my_hp = int(hp)
            # Board units: championName = "TFT_Garen" → strip prefix
            champ = player.get("championName", "")
            if champ.startswith("TFT_"):
                units.append(champ[4:])
            # items on the player unit
            break

    # Collect all TFT units across allPlayers that belong to my board
    # (allPlayers in TFT lists all units on the board as separate entries with same summonerName)
    board_units: list[str] = []
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            champ = player.get("championName", "")
            name = champ[4:] if champ.startswith("TFT_") else champ
            if name:
                board_units.append(name)

    # Recent TFT events
    events = data.get("events", {}).get("Events", [])
    _tft_notable = {"TFT_PlayerDied", "TFT_ItemPickedUp", "TFT_Augment"}
    _tft_labels = {
        "TFT_PlayerDied": "玩家淘汰",
        "TFT_ItemPickedUp": "拾取装备",
        "TFT_Augment": "选择强化",
    }
    recent = [
        _tft_labels.get(e["EventName"], e["EventName"])
        for e in events[-8:]
        if e.get("EventName") in _tft_notable
    ]

    parts = [
        "[云顶之弈]",
        f"时间{minutes}:{seconds:02d}",
        f"等级{level}",
        f"生命{my_hp}" if my_hp is not None else "",
        f"棋子{'|'.join(board_units[:6])}" if board_units else "",
    ]
    if recent:
        parts.append(f"近期{'|'.join(recent[-3:])}")
    return "，".join(p for p in parts if p)
