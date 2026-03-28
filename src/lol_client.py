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
    def get_game_summary(self, detail: str = "normal") -> str | None:
        """Return a compact Chinese game-state string, or None if not in game."""
        try:
            import requests
            data = requests.get(f"{_BASE}/allgamedata", verify=False, timeout=1).json()
            if _is_tft(data):
                return _format_tft(data, detail)
            return _format_lol(data, detail)
        except Exception:
            return None


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

    # ── minimal ──────────────────────────────────────────────────────────────
    parts = [
        f"时间{minutes}:{seconds:02d}",
        f"英雄{my_champ}" if my_champ else "",
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
            s = f"{p.get('championName','?')} {sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}"
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
            s = f"{p.get('championName','?')} {sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}"
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

def _format_tft(data: dict, detail: str = "normal") -> str:
    active = data.get("activePlayer", {})
    level = active.get("level", 1)
    gold = int(active.get("currentGold", 0))
    game_time = int(data.get("gameData", {}).get("gameTime", 0))
    minutes, seconds = divmod(game_time, 60)

    my_name = active.get("summonerName", "")

    # Collect all entries for my summoner (each unit on board is a separate entry)
    my_entries = [p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name]
    my_hp = None
    board_units: list[str] = []
    for entry in my_entries:
        hp = entry.get("championStats", {}).get("currentHealth")
        if hp is not None and my_hp is None:
            my_hp = int(hp)
        champ = entry.get("championName", "")
        name = champ[4:] if champ.startswith("TFT_") else champ
        if name:
            board_units.append(name)

    # ── minimal ──────────────────────────────────────────────────────────────
    parts = [
        "[云顶之弈]",
        f"时间{minutes}:{seconds:02d}",
        f"等级{level}",
        f"生命{my_hp}" if my_hp is not None else "",
    ]

    if detail == "minimal":
        return "，".join(p for p in parts if p)

    # ── normal ────────────────────────────────────────────────────────────────
    if board_units:
        parts.append(f"棋子{'|'.join(board_units[:6])}")

    events = data.get("events", {}).get("Events", [])
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
    parts.append(f"金币{gold}")

    if len(board_units) > 6:
        parts.append(f"全部棋子{'|'.join(board_units)}")

    # Other players' HP (standings overview), deduplicate by summonerName
    seen: set[str] = {my_name}
    others: list[tuple[str, int]] = []  # (name, hp)
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

    # All events
    if len(recent) < len(events):
        all_notable = [
            _tft_labels.get(e["EventName"], e["EventName"])
            for e in events if e.get("EventName") in _tft_notable
        ]
        if all_notable:
            parts.append(f"全部事件{'|'.join(all_notable[-5:])}")

    return "，".join(p for p in parts if p)
