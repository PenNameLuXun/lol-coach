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
        metrics = state.metrics
        hp_pct = _int(metrics.get("hp_pct"))
        mana_pct = _int(metrics.get("mana_pct"))
        gold = _int(metrics.get("gold"))
        level = _int(metrics.get("level"))
        cs = _int(metrics.get("cs"))
        game_time_seconds = _int(metrics.get("game_time_seconds"))
        position = str(metrics.get("position", ""))
        is_dead = metrics.get("is_dead") == "true"
        ally_dead = _int(state.derived.get("ally_dead"))
        enemy_dead = _int(state.derived.get("enemy_dead"))
        latest_event = str(state.derived.get("latest_event", "none"))
        event_sig = str(metrics.get("event_signature", "none"))

        game_minutes = game_time_seconds // 60

        rules: list[RuleResult] = []

        # ── 死亡 ──────────────────────────────────────────────────────────
        if is_dead:
            rules.append(RuleResult("lol_dead_reset", 98, "你已阵亡，先看小地图，复活后跟队友一起出门。", ("reset",)))

        # ── 血量危机 ──────────────────────────────────────────────────────
        if not is_dead:
            if hp_pct <= 20 and gold >= 1300:
                rules.append(RuleResult("lol_low_hp_recall_spend", 95, "残血且钱够，立刻回城补关键装，别继续贪线。", ("recall", "economy")))
            elif hp_pct <= 20:
                rules.append(RuleResult("lol_low_hp_retreat", 93, "血量极低，立刻撤到安全位置，不要贪任何东西。", ("retreat",)))
            elif hp_pct <= 35 and mana_pct <= 20:
                rules.append(RuleResult("lol_low_resources_reset", 90, "血蓝双低，先回城重置状态，再考虑接下一波。", ("reset",)))
            elif hp_pct <= 35:
                rules.append(RuleResult("lol_low_hp_safe", 85, "血量偏低，远离敌方视野，避免接受正面交战。", ("retreat",)))

        # ── 蓝量告急 ──────────────────────────────────────────────────────
        if not is_dead and mana_pct <= 15 and hp_pct >= 50:
            rules.append(RuleResult("lol_oom_warning", 78, "蓝量几乎耗尽，无法发动技能，避免接战或回城补蓝。", ("reset",)))

        # ── 团队减员与交战判断 ─────────────────────────────────────────────
        if ally_dead >= 3 and not is_dead:
            rules.append(RuleResult("lol_teamfight_wipeout", 96, "我方大量阵亡，立刻撤退守家，不要送人头。", ("disengage", "retreat")))
        elif ally_dead > enemy_dead and hp_pct <= 65:
            rules.append(RuleResult("lol_disadvantage_disengage", 88, "我方减员，别接正面，先清线撤退等队友。", ("disengage",)))
        elif ally_dead > enemy_dead and ally_dead >= 2:
            rules.append(RuleResult("lol_numbers_down_defend", 84, "我方人数劣势，守住己方防线，不要越塔推进。", ("disengage",)))

        if enemy_dead >= 3 and hp_pct >= 40 and not is_dead:
            rules.append(RuleResult("lol_ace_push", 91, "敌方团灭！立刻推进推塔，把优势转化为结构优势。", ("convert", "objective")))
        elif enemy_dead > ally_dead and hp_pct >= 45:
            rules.append(RuleResult("lol_advantage_convert", 82, "敌方减员，可先推线压塔，再转附近资源。", ("convert", "objective")))

        # ── 大龙/小龙/峡谷先锋/抑制物事件 ───────────────────────────────
        if latest_event == "BaronKill" and hp_pct >= 40 and not is_dead:
            rules.append(RuleResult("lol_baron_push", 89, "大龙刚被击杀，立刻集合开启强攻波次，推高地。", ("objective", "rotate")))
        if latest_event == "DragonKill" and hp_pct >= 45 and not is_dead:
            rules.append(RuleResult("lol_dragon_taken", 80, "龙刚有变化，向队友靠拢，准备接下来的换线或推塔。", ("rotate", "objective")))
        if latest_event == "HeraldKill" and game_minutes <= 20 and hp_pct >= 45 and not is_dead:
            rules.append(RuleResult("lol_herald_use", 83, "峡谷先锋刚击杀，尽快使用眼位/先锋打塔，不要浪费。", ("objective", "rotate")))
        if latest_event == "InhibKilled" and hp_pct >= 40 and not is_dead:
            rules.append(RuleResult("lol_inhib_push", 87, "抑制物已被摧毁，趁超级兵出现前快速推进。", ("convert", "objective")))
        if latest_event == "TurretKilled" and enemy_dead > 0 and hp_pct >= 45:
            rules.append(RuleResult("lol_turret_fallen_push", 75, "防御塔已倒，趁敌方视野空缺推进或抢资源。", ("convert", "objective")))

        # ── 金币管理 ──────────────────────────────────────────────────────
        if gold >= 2500 and hp_pct >= 40 and not is_dead:
            rules.append(RuleResult("lol_gold_overflow", 88, "金币严重积压超2500，立刻找时机回城，金币放着是浪费。", ("economy", "recall")))
        elif gold >= 1800 and hp_pct >= 35 and not is_dead:
            rules.append(RuleResult("lol_spend_gold", 72, "你身上金币很多，找安全时间窗回城更新装备。", ("economy", "recall")))
        elif gold >= 1300 and hp_pct <= 50 and not is_dead:
            rules.append(RuleResult("lol_hurt_and_rich_recall", 80, "血量偏低且攒了不少金币，这是个好时机回城。", ("economy", "recall")))

        # ── 等级差 ────────────────────────────────────────────────────────
        if level <= 5 and game_minutes >= 10:
            rules.append(RuleResult("lol_low_level_xp", 76, "等级偏低，优先刷线/野区补经验，不要轻易参与混乱团战。", ("farm",)))
        if level >= 16 and hp_pct >= 60 and gold <= 500:
            rules.append(RuleResult("lol_full_build_fight", 65, "等级较高且装备接近完整，可以主动寻找有利交战机会。", ("fight",)))

        # ── 补刀 / 时间节点 ───────────────────────────────────────────────
        if game_minutes <= 14 and cs < game_minutes * 6 and not is_dead:
            rules.append(RuleResult("lol_cs_behind", 70, f"前期补刀偏少（{cs}刀），专注清线，减少无效走动。", ("farm",)))
        if game_minutes >= 25 and cs < game_minutes * 5:
            rules.append(RuleResult("lol_late_cs_low", 62, "后期补刀仍不足，清兵线依然是被动期最稳的选择。", ("farm",)))

        # ── 时间节点提示 ──────────────────────────────────────────────────
        if game_minutes == 5 and not is_dead:
            rules.append(RuleResult("lol_early_first_back", 55, "游戏5分钟，注意首次回城时机，买核心小件再回线。", ("economy",)))
        if game_minutes >= 20 and game_minutes <= 22 and ally_dead == 0 and enemy_dead == 0:
            rules.append(RuleResult("lol_mid_game_group", 60, "中期到来，适时与队友集合，避免单人在野区被针对。", ("rotate",)))

        # ── 位置特定提示 ──────────────────────────────────────────────────
        if position == "JUNGLE" and not is_dead and game_minutes >= 3 and game_minutes % 5 == 0:
            rules.append(RuleResult("lol_jungle_objective_timer", 68, "野区资源刷新节点，提前绕路预判龙/先锋/大龙位置。", ("objective",)))
        if position == "UTILITY" and ally_dead == 0 and hp_pct >= 50 and not is_dead:
            rules.append(RuleResult("lol_support_vision", 45, "辅助多插眼控制视野，尤其是龙坑和大龙附近。", ("vision",)))

        # ── 稳定局 ────────────────────────────────────────────────────────
        if event_sig == "none" and hp_pct >= 70 and mana_pct >= 50 and enemy_dead == 0 and ally_dead == 0:
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


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
