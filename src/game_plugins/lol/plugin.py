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
        metrics = state.metrics
        hp_pct = _int(metrics.get("hp_pct"))
        mana_pct = _int(metrics.get("mana_pct"))
        gold = _int(metrics.get("gold"))
        is_dead = metrics.get("is_dead") == "true"
        ally_dead = _int(state.derived.get("ally_dead"))
        enemy_dead = _int(state.derived.get("enemy_dead"))
        latest_event = str(state.derived.get("latest_event", "none"))

        rules: list[RuleResult] = []
        if is_dead:
            rules.append(RuleResult("lol_dead_reset", 98, "你已阵亡，先看小地图，复活后跟队友一起出门。", ("reset",)))
        if hp_pct <= 20 and gold >= 1300:
            rules.append(RuleResult("lol_low_hp_recall_spend", 95, "残血且钱够，立刻回城补关键装，别继续贪线。", ("recall", "economy")))
        elif hp_pct <= 25:
            rules.append(RuleResult("lol_low_hp_retreat", 93, "血量太低，先撤到安全位置，别继续硬吃兵线。", ("retreat",)))
        if hp_pct <= 35 and mana_pct <= 20:
            rules.append(RuleResult("lol_low_resources_reset", 90, "状态太差，先回城重置血蓝，再考虑接下一波。", ("reset",)))
        if ally_dead > enemy_dead and hp_pct <= 65:
            rules.append(RuleResult("lol_disadvantage_disengage", 88, "我方减员，别接正面，先清线撤退等队友。", ("disengage",)))
        if enemy_dead > ally_dead and hp_pct >= 45:
            rules.append(RuleResult("lol_advantage_convert", 82, "敌方减员，可先推线压塔，再转附近资源。", ("convert", "objective")))
        if latest_event in {"DragonKill", "HeraldKill", "BaronKill"} and hp_pct >= 45 and not is_dead:
            rules.append(RuleResult("lol_objective_rotate", 80, "资源点刚有变化，立刻向队友靠拢，别单人乱逛。", ("rotate", "objective")))
        if gold >= 1800 and hp_pct >= 35:
            rules.append(RuleResult("lol_spend_gold", 72, "你身上金币很多，找安全时间窗回城更新装备。", ("economy", "recall")))
        if metrics.get("event_signature", "none") == "none" and hp_pct >= 70 and mana_pct >= 50 and enemy_dead == 0 and ally_dead == 0:
            rules.append(RuleResult("lol_stable_farm", 40, "局势平稳，优先补刀控线，等下一次资源刷新。", ("farm", "tempo")))
        return rules

    def render_advice(self, rule: RuleResult, state: GameState) -> str:
        return rule.message

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

    def build_ai_context(self, state: GameState) -> str:
        return (
            f"规则观察：最近事件{state.derived.get('latest_event', 'none')}，"
            f"我方阵亡{state.derived.get('ally_dead', 0)}人，"
            f"敌方阵亡{state.derived.get('enemy_dead', 0)}人。"
        )

    def build_rule_hint(self, rule: RuleResult, state: GameState, rendered_advice: str) -> str:
        return f"{rendered_advice} {self.build_ai_context(state)}"

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


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
