"""League of Legends / TFT Live Client Data API client.

Fetches real-time game state from the local API exposed by the LOL process
at https://127.0.0.1:2999 during an active game.

Auto-detects TFT vs normal LOL from the response data.
Returns None when not in game (connection refused / timeout).

detail levels (lol_client.detail in config.yaml):
  minimal — time, champion, level, HP, gold
  normal  — + mana, items, recent events          (default)
  full    — + KDA, CS, wards, spells, rune, all allies/enemies, dragon type
"""

import urllib3
import urllib3.exceptions

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE = "https://127.0.0.1:2999/liveclientdata"


class LolClient:
    def __init__(self):
        self.last_seen_in_game = False  # True once a live game was detected

    def get_live_data(self) -> dict | None:
        """Return raw live client payload, or None if not in game / game over."""
        try:
            import requests
            data = requests.get(f"{_BASE}/allgamedata", verify=False, timeout=1).json()
            events = data.get("events", {}).get("Events", [])
            if any(e.get("EventName") == "GameEnd" for e in events):
                return None
            self.last_seen_in_game = True
            return data
        except Exception:
            return None

    def get_game_summary(self, detail: str = "normal") -> str | None:
        """Return a compact Chinese game-state string, or None if not in game or game is over."""
        data = self.get_live_data()
        if data is None:
            return None
        return summarize_game_data(data, detail)

    def get_player_address(self, address_by: str = "champion") -> str | None:
        """Return the name to address the player by, or None if not in game."""
        data = self.get_live_data()
        if data is None:
            return None
        return get_player_address_from_data(data, address_by)


def summarize_game_data(data: dict, detail: str = "normal") -> str:
    if detect_game_type(data) == "tft":
        return _format_tft(data, detail)
    return _format_lol(data, detail)


def detect_game_type(data: dict) -> str:
    return "tft" if _is_tft(data) else "lol"


def get_player_address_from_data(data: dict, address_by: str = "champion") -> str | None:
    """Return the name to address the player by, or None if not in game."""
    if address_by == "none":
        return None
    active = data.get("activePlayer", {})
    my_name = active.get("summonerName", "")
    if address_by == "summoner":
        return my_name or None
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            champ = player.get("championName", "")
            return champ[4:] if champ.startswith("TFT_") else champ or None
    return my_name or None


def extract_key_metrics(data: dict) -> dict[str, int | str]:
    """Return normalized metrics used for prompt assembly and trend tracking."""
    active = data.get("activePlayer", {})
    stats = active.get("championStats", {})
    game_time_seconds = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time_seconds, 60)

    my_name = active.get("summonerName", "")
    my_player = next((p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name), {})
    my_scores = my_player.get("scores", {})

    hp = int(stats.get("currentHealth", 0))
    max_hp = int(stats.get("maxHealth", 1) or 1)
    resource = int(stats.get("resourceValue", 0))
    max_resource = int(stats.get("resourceMax", 0) or 0)
    events = data.get("events", {}).get("Events", [])
    notable_events = [
        e.get("EventName", "")
        for e in events[-6:]
        if e.get("EventName") in {"DragonKill", "BaronKill", "HeraldKill", "TurretKilled", "ChampionKill", "InhibKilled"}
    ]

    return {
        "game_type": detect_game_type(data),
        "game_time_seconds": game_time_seconds,
        "game_time": f"{minutes}:{seconds:02d}",
        "gold": int(active.get("currentGold", 0)),
        "level": int(active.get("level", 1)),
        "hp_pct": int(hp / max_hp * 100) if max_hp else 0,
        "mana_pct": int(resource / max_resource * 100) if max_resource else 0,
        "kda": f"{my_scores.get('kills', 0)}/{my_scores.get('deaths', 0)}/{my_scores.get('assists', 0)}",
        "cs": int(my_scores.get("creepScore", 0)),
        "champion": my_player.get("championName", ""),
        "position": my_player.get("position", ""),
        "mode": data.get("gameData", {}).get("gameMode", ""),
        "event_signature": "|".join(notable_events[-3:]) if notable_events else "none",
        "is_dead": "true" if my_player.get("isDead") else "false",
    }


_POS_MAP = {
    "TOP": "上路", "JUNGLE": "打野", "MIDDLE": "中路",
    "BOTTOM": "下路", "UTILITY": "辅助",
}

# ── Detection ─────────────────────────────────────────────────────────────────

def _is_tft(data: dict) -> bool:
    mode = data.get("gameData", {}).get("gameMode", "").upper()
    if mode == "TFT":
        return True
    players = data.get("allPlayers", [])
    return bool(players and players[0].get("championName", "").startswith("TFT_"))


# ── LOL formatter ─────────────────────────────────────────────────────────────

def _format_lol(data: dict, detail: str = "normal") -> str:
    active = data.get("activePlayer", {})
    stats = active.get("championStats", {})
    game_time = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time, 60)

    hp = stats.get("currentHealth", 0)
    max_hp = stats.get("maxHealth", 1)
    hp_pct = int(hp / max_hp * 100)
    gold = int(active.get("currentGold", 0))
    level = active.get("level", 1)

    my_name = active.get("summonerName", "")
    my_player = next((p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name), {})
    my_champ = my_player.get("championName", "")
    my_team = my_player.get("team", "ORDER")
    my_position = my_player.get("position", "")

    # ── minimal ──────────────────────────────────────────────────────────────
    pos_label = _POS_MAP.get(my_position.upper(), "")

    parts = [
        f"时间{minutes}:{seconds:02d}",
        f"英雄{my_champ}" if my_champ else "",
        f"分路{pos_label}" if pos_label else "",
        f"等级{level}",
        f"血{hp_pct}%",
        f"金币{gold}",
    ]

    if detail == "minimal":
        return "，".join(p for p in parts if p)

    # ── normal ────────────────────────────────────────────────────────────────
    mana = stats.get("resourceValue", 0)
    max_mana = stats.get("resourceMax", 1)
    mana_pct = int(mana / max_mana * 100) if max_mana else 0
    items = [i["displayName"] for i in my_player.get("items", []) if i.get("displayName")]

    if mana_pct:
        parts.append(f"蓝{mana_pct}%")
    parts.append(f"装备{'|'.join(items[:4])}" if items else "无装备")

    events = data.get("events", {}).get("Events", [])
    _notable = {"DragonKill", "BaronKill", "TurretKilled", "ChampionKill", "InhibKilled", "HeraldKill"}
    _labels = {
        "DragonKill": "击杀龙", "BaronKill": "击杀大龙", "TurretKilled": "推塔",
        "ChampionKill": "击杀英雄", "InhibKilled": "推水晶", "HeraldKill": "击杀先锋",
    }
    recent = [_labels[e["EventName"]] for e in events[-8:] if e.get("EventName") in _notable]
    if recent:
        parts.append(f"近期{'|'.join(recent[-3:])}")

    if detail == "normal":
        return "，".join(p for p in parts if p)

    # ── full ──────────────────────────────────────────────────────────────────
    scores = my_player.get("scores", {})
    kda = f"{scores.get('kills',0)}/{scores.get('deaths',0)}/{scores.get('assists',0)}"
    cs = scores.get("creepScore", 0)
    wards = scores.get("wardScore", 0)
    parts.append(f"KDA{kda}")
    parts.append(f"补刀{cs}")
    if wards:
        parts.append(f"视野{int(wards)}")

    spells = my_player.get("summonerSpells", {})
    spell_names = [v.get("displayName", "") for v in spells.values() if isinstance(v, dict)]
    if spell_names:
        parts.append(f"召唤师技能{'|'.join(spell_names)}")

    keystone = active.get("fullRunes", {}).get("keystone", {}).get("displayName", "")
    if keystone:
        parts.append(f"符文{keystone}")

    if len(items) > 4:
        parts.append(f"全装备{'|'.join(items)}")

    # Allies
    allies = [
        p for p in data.get("allPlayers", [])
        if p.get("team") == my_team and p.get("summonerName") != my_name
    ]
    if allies:
        ally_strs = []
        for p in allies:
            sc = p.get("scores", {})
            pos = _POS_MAP.get(p.get("position", "").upper(), "")
            s = f"{p.get('championName','?')}({pos})" if pos else f"{p.get('championName','?')}"
            s += f" {sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}"
            if p.get("isDead"):
                s += f"(复活{p.get('respawnTimer',0):.0f}s)"
            ally_strs.append(s)
        parts.append(f"队友：{'  '.join(ally_strs)}")

    # Enemies
    enemies = [p for p in data.get("allPlayers", []) if p.get("team") != my_team]
    if enemies:
        enemy_strs = []
        for p in enemies:
            sc = p.get("scores", {})
            pos = _POS_MAP.get(p.get("position", "").upper(), "")
            s = f"{p.get('championName','?')}({pos})" if pos else f"{p.get('championName','?')}"
            s += f" {sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}"
            if p.get("isDead"):
                s += f"(复活{p.get('respawnTimer',0):.0f}s)"
            enemy_strs.append(s)
        parts.append(f"敌方：{'  '.join(enemy_strs)}")

    # Dragon types in recent events
    dragon_events = [
        e for e in events if e.get("EventName") == "DragonKill"
    ]
    if dragon_events:
        dragon_types = [e.get("DragonType", "") for e in dragon_events[-3:]]
        parts.append(f"已击杀龙：{'|'.join(t for t in dragon_types if t)}")

    return "，".join(p for p in parts if p)


# ── TFT formatter ─────────────────────────────────────────────────────────────

def _tft_unit_str(entry: dict, with_items: bool = False) -> str:
    """Format a single TFT board unit, optionally with its items."""
    champ = entry.get("championName", "")
    name = champ[4:] if champ.startswith("TFT_") else champ
    if not name:
        return ""
    if with_items:
        item_names = [i["displayName"] for i in entry.get("items", []) if i.get("displayName")]
        if item_names:
            return f"{name}({'+'.join(item_names)})"
    return name


def _format_tft(data: dict, detail: str = "normal") -> str:
    active = data.get("activePlayer", {})
    level = active.get("level", 1)
    gold = int(active.get("currentGold", 0))
    interest = min(gold // 10, 5)  # interest income: 1g per 10g, capped at 5
    game_time = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time, 60)

    my_name = active.get("summonerName", "")

    # Collect all entries for my summoner (each unit on board is a separate entry)
    my_entries = [p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name]
    my_hp = None
    for entry in my_entries:
        hp = entry.get("championStats", {}).get("currentHealth")
        if hp is not None and my_hp is None:
            my_hp = int(hp)

    events = data.get("events", {}).get("Events", [])

    # Count alive players (those with hp > 0, deduplicated by summonerName)
    seen_names: set[str] = set()
    alive_count = 0
    for p in data.get("allPlayers", []):
        n = p.get("summonerName", "")
        if n in seen_names:
            continue
        seen_names.add(n)
        hp = p.get("championStats", {}).get("currentHealth", 0)
        if (hp or 0) > 0:
            alive_count += 1

    # ── minimal ──────────────────────────────────────────────────────────────
    parts = [
        "[云顶之弈]",
        f"时间{minutes}:{seconds:02d}",
        f"等级{level}",
        f"金币{gold}(利息{interest})",
        f"生命{my_hp}" if my_hp is not None else "",
        f"存活{alive_count}人" if alive_count else "",
    ]

    if detail == "minimal":
        return "，".join(p for p in parts if p)

    # ── normal ────────────────────────────────────────────────────────────────
    # Board units with items (up to 6)
    board_strs = [_tft_unit_str(e, with_items=True) for e in my_entries]
    board_strs = [s for s in board_strs if s]
    if board_strs:
        parts.append(f"棋子{'|'.join(board_strs[:6])}")

    # Augments chosen (extract augment name from events)
    augments = [
        e.get("Augment", e.get("augment", "强化"))
        for e in events if e.get("EventName") == "TFT_Augment"
    ]
    if augments:
        parts.append(f"已选强化{'|'.join(augments)}")

    _tft_notable = {"TFT_PlayerDied", "TFT_ItemPickedUp", "TFT_Augment"}
    _tft_labels = {
        "TFT_PlayerDied": "玩家淘汰", "TFT_ItemPickedUp": "拾取装备", "TFT_Augment": "选择强化",
    }
    recent = [
        _tft_labels.get(e["EventName"], e["EventName"])
        for e in events[-8:] if e.get("EventName") in _tft_notable
    ]
    if recent:
        parts.append(f"近期{'|'.join(recent[-3:])}")

    if detail == "normal":
        return "，".join(p for p in parts if p)

    # ── full ──────────────────────────────────────────────────────────────────
    # All board units with items if more than 6
    if len(board_strs) > 6:
        parts.append(f"全部棋子{'|'.join(board_strs)}")

    # Other players' HP standings, deduplicated by summonerName
    seen: set[str] = {my_name}
    others: list[tuple[str, int]] = []
    for p in data.get("allPlayers", []):
        name = p.get("summonerName", "")
        if name in seen:
            continue
        seen.add(name)
        hp = p.get("championStats", {}).get("currentHealth")
        if hp is not None:
            others.append((name, int(hp)))
    if others:
        others.sort(key=lambda x: x[1], reverse=True)
        standings = "  ".join(f"{n}:{h}" for n, h in others[:7])
        parts.append(f"其他玩家生命：{standings}")

    # All notable events
    all_notable = [
        _tft_labels.get(e["EventName"], e["EventName"])
        for e in events if e.get("EventName") in _tft_notable
    ]
    if all_notable:
        parts.append(f"全部事件{'|'.join(all_notable[-5:])}")

    return "，".join(p for p in parts if p)
