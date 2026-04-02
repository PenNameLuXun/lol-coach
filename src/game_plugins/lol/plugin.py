from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.base import AiPayload, GameState, RuleResult
from src.game_plugins.league_shared.live_client import (
    detect_game_type,
    extract_key_metrics,
    get_player_address_from_data,
    summarize_game_data,
)
from src.game_plugins.lol.prompting import (
    build_bridge_prompt,
    build_decision_prompt,
    render_history_context,
)
from src.game_plugins.lol.rules import build_lol_rule_hint, evaluate_lol_rules
from src.game_plugins.lol.source import LolLiveDataSource


class LolPlugin:
    id = "lol"
    display_name = "League of Legends"
    manifest = {
        "id": "lol",
        "display_name": "League of Legends",
        "source": {"kind": "league_live_client"},
        "supports_rules": True,
        "supports_ai_context": True,
        "capabilities": {"ai": True, "rules": True, "visual": True},
        "config_schema": [
            {
                "key": "detail",
                "label": "数据细节",
                "type": "select",
                "options": ["minimal", "normal", "full"],
                "default": "full",
                "help": "控制发送给 AI 的局势摘要粒度。",
            },
            {
                "key": "address_by",
                "label": "玩家称呼",
                "type": "select",
                "options": ["champion", "summoner", "none"],
                "default": "champion",
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
                "default": "你是一个英雄联盟教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条对局建议。",
                "help": "LoL 插件专属系统提示词。",
            },
            {
                "key": "trigger_force_after_seconds",
                "label": "强制分析秒数",
                "type": "int",
                "default": 45,
                "min": 1,
                "max": 600,
                "help": "超过该秒数后，即使局势平稳也强制分析一次。",
            },
            {
                "key": "trigger_hp_drop_pct",
                "label": "血量下降阈值",
                "type": "int",
                "default": 20,
                "min": 0,
                "max": 100,
                "help": "血量下降达到该百分比时触发分析。",
            },
            {
                "key": "trigger_gold_delta",
                "label": "金币变化阈值",
                "type": "int",
                "default": 350,
                "min": 0,
                "max": 5000,
                "help": "金币增长达到该值时触发分析。",
            },
            {
                "key": "trigger_cs_delta",
                "label": "补刀变化阈值",
                "type": "int",
                "default": 8,
                "min": 0,
                "max": 200,
                "help": "补刀变化达到该值时触发分析。",
            },
            {
                "key": "trigger_skip_stable_cycles",
                "label": "跳过稳定周期",
                "type": "bool",
                "default": True,
                "help": "启用后，局势平稳时会跳过本轮分析。",
            },
        ],
    }

    def __init__(self):
        self._source = LolLiveDataSource()

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        return detect_game_type(raw_data) == "lol"

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        metrics = metrics or extract_key_metrics(raw_data)
        my_player = _get_my_player(raw_data)
        ally_dead, enemy_dead = _team_death_counts(
            raw_data,
            my_player.get("team", "ORDER"),
            my_player.get("summonerName", ""),
        )
        latest_event = _latest_notable_event(raw_data) or "none"
        derived = {
            "ally_dead": ally_dead,
            "enemy_dead": enemy_dead,
            "latest_event": latest_event,
        }
        return GameState(plugin_id=self.id, game_type="lol", raw_data=raw_data, metrics=metrics, derived=derived)

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        return evaluate_lol_rules(state)

    def build_ai_payload(
        self,
        state: GameState,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> AiPayload:
        return AiPayload(
            game_summary=summarize_game_data(state.raw_data, detail=detail),
            address=get_player_address_from_data(state.raw_data, address_by),
            metrics=dict(state.metrics),
        )

    def build_rule_hint(self, rule: RuleResult, state: GameState) -> str:
        return build_lol_rule_hint(rule, state)

    def wants_visual_context(self, state: GameState) -> bool:
        return True

    def build_vision_prompt(self, state: GameState, detail: str = "normal") -> str:
        payload = self.build_ai_payload(state, detail=detail)
        return build_bridge_prompt(payload.game_summary, payload.metrics)

    def build_history_context(self, snapshots: list[AnalysisSnapshot]) -> str:
        return render_history_context(snapshots)

    def build_decision_prompt(
        self,
        state: GameState,
        system_prompt: str,
        bridge_facts: dict[str, str] | None,
        snapshots: list[AnalysisSnapshot],
        rule_hint: str | None = None,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> str:
        payload = self.build_ai_payload(state, detail=detail, address_by=address_by)
        return build_decision_prompt(
            system_prompt=system_prompt,
            game_summary=payload.game_summary,
            address=payload.address,
            metrics=payload.metrics,
            bridge_facts=bridge_facts,
            historical_context=self.build_history_context(snapshots),
            rule_hint=rule_hint,
        )


def _get_my_player(data: dict) -> dict:
    active = data.get("activePlayer", {})
    my_name = active.get("summonerName", "")
    return next((p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name), {})


def _team_death_counts(data: dict, my_team: str, my_name: str) -> tuple[int, int]:
    ally_dead = 0
    enemy_dead = 0
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == my_name:
            continue
        if player.get("team") == my_team:
            ally_dead += 1 if player.get("isDead") else 0
        else:
            enemy_dead += 1 if player.get("isDead") else 0
    return ally_dead, enemy_dead


def _latest_notable_event(data: dict) -> str | None:
    notable = {"DragonKill", "BaronKill", "HeraldKill", "TurretKilled", "ChampionKill", "InhibKilled"}
    for event in reversed(data.get("events", {}).get("Events", [])):
        name = event.get("EventName")
        if name in notable:
            return name
    return None
