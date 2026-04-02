from src.game_plugins.base import AiPayload, GameState, RuleResult
from src.game_plugins.league_shared.live_client import (
    detect_game_type,
    extract_key_metrics,
    get_player_address_from_data,
    summarize_game_data,
)
from src.game_plugins.tft.prompting import (
    build_tft_decision_prompt,
    build_tft_vision_prompt,
    render_shop_units,
    render_traits,
)
from src.game_plugins.tft.rules import build_tft_rule_hint, evaluate_tft_rules
from src.game_plugins.tft.source import TftLiveDataSource


class TftPlugin:
    id = "tft"
    display_name = "Teamfight Tactics"
    manifest = {
        "id": "tft",
        "display_name": "Teamfight Tactics",
        "source": {"kind": "league_live_client"},
        "supports_rules": True,
        "supports_ai_context": True,
        "capabilities": {"ai": True, "rules": True, "visual": True},
        "config_schema": [
            {
                "key": "data_source",
                "label": "实时数据源",
                "type": "select",
                "options": ["riot_live_client", "overwolf", "hybrid"],
                "default": "riot_live_client",
                "help": "riot_live_client 使用官方本地接口；overwolf 仅走 Overwolf bridge；hybrid 优先合并两者。",
            },
            {
                "key": "detail",
                "label": "数据细节",
                "type": "select",
                "options": ["minimal", "normal", "full"],
                "default": "normal",
                "help": "控制发送给 AI 的云顶摘要粒度。",
            },
            {
                "key": "address_by",
                "label": "玩家称呼",
                "type": "select",
                "options": ["champion", "summoner", "none"],
                "default": "summoner",
                "help": "AI 回复中如何称呼玩家。",
            },
            {
                "key": "require_game",
                "label": "必须在对局中",
                "type": "bool",
                "default": True,
                "help": "启用后仅在检测到活跃对局时分析。",
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "text",
                "default": "你是一个云顶之弈教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条建议，例如该买什么英雄、阵容方向、经济决策等。",
                "help": "TFT 插件专属系统提示词。",
            },
        ],
    }

    def __init__(self, config=None):
        self._source = TftLiveDataSource()
        data_source = "riot_live_client"
        overwolf_enabled = False
        host = "127.0.0.1"
        port = 7799
        stale_after_seconds = 5
        if config is not None:
            data_source = str(config.plugin_setting(self.id, "data_source", "riot_live_client"))
            ow_cfg = config.overwolf or {}
            overwolf_enabled = bool(ow_cfg.get("enabled", False))
            host = str(ow_cfg.get("host", host))
            port = int(ow_cfg.get("port", port))
            stale_after_seconds = int(ow_cfg.get("stale_after_seconds", stale_after_seconds))
        self._source.configure(
            data_source=data_source,
            overwolf_enabled=overwolf_enabled,
            host=host,
            port=port,
            stale_after_seconds=stale_after_seconds,
        )

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        if raw_data.get("_game_type") == "tft":
            return True
        return detect_game_type(raw_data) == "tft"

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        metrics = metrics or _extract_tft_metrics(raw_data)
        active = raw_data.get("activePlayer", {})
        ow = raw_data.get("_overwolf")

        if ow:
            hp = int(ow.get("hp", 100))
            gold = int(ow.get("gold", 0))
            level = int(ow.get("level", 1))
            alive = int(ow.get("alive_players", 0))
            source = "overwolf"
        else:
            hp = _find_tft_hp(raw_data, active.get("summonerName", ""))
            alive = _count_tft_alive(raw_data)
            raw_gold = int(active.get("currentGold", 0) or 0)
            gold = raw_gold if raw_gold <= 100 else 0
            level = int(active.get("level", 1) or 1)
            source = "riot"

        print(f"[TFT state:{source}] hp={hp} gold={gold} level={level} alive={alive}")
        return GameState(
            plugin_id=self.id,
            game_type="tft",
            raw_data=raw_data,
            metrics=metrics,
            derived={
                "player_hp": hp,
                "alive_players": alive,
                "level": level,
                "gold": gold,
                "shop": ow.get("shop", []) if ow else [],
                "board": ow.get("board", []) if ow else [],
                "bench": ow.get("bench", []) if ow else [],
                "traits": ow.get("traits", []) if ow else [],
                "round": ow.get("round", "") if ow else "",
                "data_source": source,
            },
        )

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        return evaluate_tft_rules(state)

    def build_ai_payload(
        self,
        state: GameState,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> AiPayload:
        if state.derived.get("data_source") == "overwolf":
            hp = state.derived.get("player_hp", "?")
            gold = state.derived.get("gold", "?")
            level = state.derived.get("level", "?")
            alive = state.derived.get("alive_players", "?")
            round_name = state.derived.get("round", "") or "unknown"
            summary = (
                f"云顶之弈实时数据（Overwolf）：血量{hp}，金币{gold}，等级{level}，"
                f"剩余玩家{alive}，当前回合{round_name}。"
            )
            if state.derived.get("shop"):
                summary += f" 商店：{render_shop_units(state.derived.get('shop', []))}。"
            if state.derived.get("traits"):
                summary += f" 羁绊：{render_traits(state.derived.get('traits', []))}。"
            address = state.raw_data.get("_overwolf", {}).get("me", {}).get("name")
            return AiPayload(
                game_summary=summary,
                address=address if address_by != "none" else None,
                metrics=dict(state.metrics),
            )
        return AiPayload(
            game_summary=summarize_game_data(state.raw_data, detail=detail),
            address=get_player_address_from_data(state.raw_data, address_by),
            metrics=dict(state.metrics),
        )

    def build_rule_hint(self, rule: RuleResult, state: GameState) -> str:
        return build_tft_rule_hint(rule, state)

    def wants_visual_context(self, state: GameState) -> bool:
        return True

    def build_vision_prompt(self, state: GameState, detail: str = "normal") -> str:
        return build_tft_vision_prompt(self.build_ai_payload(state, detail=detail))

    def build_decision_prompt(
        self,
        state: GameState,
        system_prompt: str,
        bridge_facts: dict[str, str] | None,
        snapshots,
        rule_hint: str | None = None,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> str:
        payload = self.build_ai_payload(state, detail=detail, address_by=address_by)
        return build_tft_decision_prompt(
            system_prompt=system_prompt,
            payload=payload,
            bridge_facts=bridge_facts,
            snapshots=snapshots,
            rule_hint=rule_hint,
        )


def _find_tft_hp(data: dict, summoner_name: str) -> int:
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == summoner_name:
            hp = player.get("championStats", {}).get("currentHealth")
            if hp is not None:
                return int(hp)
    return 100


def _count_tft_alive(data: dict) -> int:
    seen: set[str] = set()
    alive = 0
    for player in data.get("allPlayers", []):
        name = player.get("summonerName", "")
        if not name or name in seen:
            continue
        seen.add(name)
        hp = int(player.get("championStats", {}).get("currentHealth", 0) or 0)
        if hp > 0:
            alive += 1
    total = len(set(p.get("summonerName", "") for p in data.get("allPlayers", []) if p.get("summonerName")))
    if alive == 0 and total > 0:
        return 0
    return alive


def _extract_tft_metrics(raw_data: dict) -> dict[str, int | str]:
    if raw_data.get("_game_type") == "tft" and raw_data.get("_source") == "overwolf":
        ow = raw_data.get("_overwolf", {})
        return {
            "game_type": "tft",
            "game_time_seconds": int(ow.get("game_time_seconds", 0) or 0),
            "game_time": str(ow.get("game_time", "?")),
            "gold": int(ow.get("gold", 0) or 0),
            "level": int(ow.get("level", 1) or 1),
            "hp_pct": int(ow.get("hp", 100) or 0),
            "mana_pct": 0,
            "kda": "-",
            "cs": 0,
            "champion": "",
            "position": "",
            "mode": str(ow.get("mode", "TFT")),
            "event_signature": str(ow.get("event_signature", "none")),
            "is_dead": "false",
        }
    return extract_key_metrics(raw_data)
