"""League of Legends Live Client Data API client.

Fetches real-time game state from the local API exposed by the LOL process
at https://127.0.0.1:2999 during an active game.

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
            return _format(data)
        except Exception:
            return None


def _format(data: dict) -> str:
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
    team = ""
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            my_champ = player.get("championName", "")
            items = [
                i["displayName"] for i in player.get("items", [])
                if i.get("displayName")
            ]
            team = player.get("team", "")
            break

    # recent notable events
    events = data.get("events", {}).get("Events", [])
    _notable = {"DragonKill", "BaronKill", "TurretKilled", "ChampionKill", "InhibKilled", "HeraldKill"}
    _labels = {
        "DragonKill": "击杀龙", "BaronKill": "击杀大龙", "TurretKilled": "推塔",
        "ChampionKill": "击杀英雄", "InhibKilled": "推水晶", "HeraldKill": "击杀先锋",
    }
    recent = [
        _labels[e["EventName"]]
        for e in events[-8:]
        if e.get("EventName") in _notable
    ]

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
