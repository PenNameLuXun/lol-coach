from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.base import AiPayload, GameState, RuleResult
from src.game_plugins.league_shared.live_client import (
    detect_game_type,
    extract_key_metrics,
    get_player_address_from_data,
    summarize_game_data,
)
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

    def __init__(self):
        self._source = TftLiveDataSource()

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        return detect_game_type(raw_data) == "tft"

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        metrics = metrics or extract_key_metrics(raw_data)
        active = raw_data.get("activePlayer", {})
        hp = _find_tft_hp(raw_data, active.get("summonerName", ""))
        alive = _count_tft_alive(raw_data)
        derived = {
            "player_hp": hp,
            "alive_players": alive,
            "level": int(active.get("level", 1) or 1),
            "gold": int(active.get("currentGold", 0) or 0),
        }
        return GameState(plugin_id=self.id, game_type="tft", raw_data=raw_data, metrics=metrics, derived=derived)

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        hp = _int(state.derived.get("player_hp"))
        gold = _int(state.derived.get("gold"))
        level = _int(state.derived.get("level"))
        alive = _int(state.derived.get("alive_players"))
        game_time_seconds = _int(state.metrics.get("game_time_seconds"))
        game_minutes = game_time_seconds // 60

        # 利息档位：10/20/30/40/50 金每档+1利息
        interest_tier = min(gold // 10, 5)
        # 距下一档差几金
        next_tier_gap = (interest_tier + 1) * 10 - gold if interest_tier < 5 else 0

        rules: list[RuleResult] = []

        # ── 血量危机 ──────────────────────────────────────────────────────
        if hp <= 15:
            rules.append(RuleResult("tft_critical_hp", 99, f"血量仅剩{hp}，必须全力D牌提战力，经济已无意义。", ("roll", "survival")))
        elif hp <= 25 and gold >= 20:
            rules.append(RuleResult("tft_low_hp_roll", 96, f"血量{hp}危险，别再贪利息，立刻搜牌保血。", ("roll", "survival")))
        elif hp <= 35 and gold >= 30:
            rules.append(RuleResult("tft_warn_hp_roll", 90, f"血量{hp}偏低，考虑搜牌稳住阵容，避免再被打崩。", ("roll", "survival")))
        elif hp <= 40 and gold >= 50:
            rules.append(RuleResult("tft_convert_econ", 88, "血量开始危险，把50金的一部分转成战力，先保血。", ("economy", "survival")))

        # ── 利息管理 ──────────────────────────────────────────────────────
        if gold >= 50 and hp >= 45:
            rules.append(RuleResult("tft_hold_interest", 74, "经济满50，继续吃满利息，别急着乱D。", ("economy",)))
        elif gold >= 40 and hp >= 50 and next_tier_gap <= 0:
            rules.append(RuleResult("tft_hold_40_interest", 68, "守住40金利息档，每回合多1金，不要随意花费。", ("economy",)))
        elif 1 <= next_tier_gap <= 3 and hp >= 50 and gold < 50:
            rules.append(RuleResult("tft_interest_threshold", 66, f"再存{next_tier_gap}金就到下一利息档，尽量别在这里乱花。", ("economy",)))
        if gold <= 10 and hp >= 55 and level <= 7:
            rules.append(RuleResult("tft_rebuild_econ", 64, "经济偏薄，先稳住节奏，别在弱势回合硬搜。", ("economy", "tempo")))
        if gold <= 5 and hp <= 50:
            rules.append(RuleResult("tft_broke_low_hp", 85, "金币和血量双低，局势非常被动，专注下回合稳住阵型。", ("survival",)))

        # ── 升级人口时机 ──────────────────────────────────────────────────
        if level <= 5 and game_minutes >= 9 and gold >= 20 and hp >= 50:
            rules.append(RuleResult("tft_level_up_5", 78, "局势稳定，可以考虑升到5级解锁更多棋子槽位。", ("level", "tempo")))
        if level == 6 and game_minutes >= 14 and gold >= 30 and hp >= 45:
            rules.append(RuleResult("tft_level_up_7", 76, "已6级，条件允许时升7级可提升出3费棋的概率。", ("level", "tempo")))
        if level == 7 and alive <= 5 and gold >= 40 and hp >= 40:
            rules.append(RuleResult("tft_level_up_8", 80, "进入后期，升8级能大幅提升出4费棋的概率，时机合适就升。", ("level", "top4")))
        if level >= 8 and gold >= 50 and hp >= 30 and alive <= 4:
            rules.append(RuleResult("tft_level_9_push", 72, "经济充裕，可以考虑冲9级，出5费棋概率大幅提升。", ("level", "top4")))

        # ── 搜牌时机 ──────────────────────────────────────────────────────
        if level >= 7 and gold >= 30 and hp <= 55 and alive >= 5:
            rules.append(RuleResult("tft_slow_roll_7", 77, "7级搜牌效率高，血量有压力时可以慢滚找3费3星。", ("roll",)))
        if level == 8 and gold >= 40 and hp <= 60:
            rules.append(RuleResult("tft_roll_8_4cost", 79, "8级出4费棋概率最高，可以搜找核心4费。", ("roll",)))
        if gold >= 60 and hp <= 45:
            rules.append(RuleResult("tft_must_roll", 92, f"金币{gold}积压且血量偏低，必须搜牌提升战力了。", ("roll", "survival")))

        # ── 决赛圈 ────────────────────────────────────────────────────────
        if alive <= 4 and gold >= 30:
            rules.append(RuleResult("tft_top4_push", 82, "已进决赛圈，别再纯贪经济，开始保血提质量。", ("top4", "tempo")))
        if alive <= 3 and hp <= 30:
            rules.append(RuleResult("tft_final_all_in", 95, "决赛圈且血量危急，放手一搏全力D牌，争取吃鸡。", ("roll", "survival", "top4")))
        if alive <= 2:
            rules.append(RuleResult("tft_final_fight", 97, "最终对决！全力优化站位和阵容，每一格都很关键。", ("top4", "positioning")))

        # ── 连胜/连败经济策略 ─────────────────────────────────────────────
        if hp >= 85 and gold >= 30 and alive >= 6:
            rules.append(RuleResult("tft_win_streak_greed", 62, "血量充足，你可能在连胜，继续贪经济到50再搜。", ("economy",)))
        if hp <= 60 and gold >= 40 and alive >= 6 and level <= 6:
            rules.append(RuleResult("tft_lose_streak_dilemma", 70, "血量受损且金币充裕，考虑适当投资提升阵容强度打破连败。", ("roll", "economy")))

        # ── 阶段节点提示 ──────────────────────────────────────────────────
        if game_minutes <= 4 and level <= 3:
            rules.append(RuleResult("tft_early_econ", 50, "对局初期，优先建立经济，不要轻易花钱升级。", ("economy",)))
        if 9 <= game_minutes <= 11 and level <= 5:
            rules.append(RuleResult("tft_stage3_transition", 60, "进入第三阶段，注意阵容方向，开始朝核心羁绊靠拢。", ("tempo",)))
        if game_minutes >= 20 and level <= 6:
            rules.append(RuleResult("tft_late_level_warn", 75, "后期人口偏低，抓紧升级或调整策略，别落后太多。", ("level", "tempo")))

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
            f"规则观察：当前生命{state.derived.get('player_hp', '?')}，"
            f"存活玩家{state.derived.get('alive_players', '?')}，"
            f"金币{state.derived.get('gold', '?')}。"
        )

    def build_rule_hint(self, rule: RuleResult, state: GameState, rendered_advice: str) -> str:
        return f"{rendered_advice} {self.build_ai_context(state)}"

    def wants_visual_context(self, state: GameState) -> bool:
        return True

    def build_vision_prompt(self, state: GameState, detail: str = "normal") -> str:
        payload = self.build_ai_payload(state, detail=detail)
        return (
            "你是云顶之弈视觉核验模块，只做高置信事实提取，不做解释。\n"
            "请根据截图输出严格键值对，每行一个字段，不要补充额外内容。\n"
            "字段必须完整输出：\n"
            "board_strength: weak|stable|strong|unknown\n"
            "economy_state: broke|stabilizing|healthy|rich|unknown\n"
            "upgrade_window: roll_now|level_now|hold|unknown\n"
            "streak_state: win|lose|none|unknown\n"
            "contest_pressure: low|medium|high|unknown\n"
            "positioning_risk: low|medium|high|unknown\n"
            "item_clarity: clear|unclear|unknown\n"
            "confidence: high|medium|low\n"
            "focus: 用不超过12字写出当前最值得关注的点\n"
            "evidence: 用不超过24字写出你最确信的依据\n\n"
            f"已知摘要：{payload.game_summary or '无'}\n"
            f"关键数值：时间{payload.metrics.get('game_time', '?')} 金币{payload.metrics.get('gold', '?')} "
            f"等级{payload.metrics.get('level', '?')} 模式{payload.metrics.get('mode', '?')}\n"
            "如果截图无法确认阵容、装备或站位，请把字段写 unknown，并降低 confidence。"
        )

    def build_history_context(self, snapshots: list[AnalysisSnapshot]) -> str:
        if not snapshots:
            return "无历史上下文。"
        oldest = snapshots[0]
        latest = snapshots[-1]
        lines: list[str] = []

        old_gold = oldest.metrics.get("gold")
        new_gold = latest.metrics.get("gold")
        if isinstance(old_gold, int) and isinstance(new_gold, int):
            lines.append(f"金币变化 {new_gold - old_gold:+d}")

        old_level = oldest.metrics.get("level")
        new_level = latest.metrics.get("level")
        if isinstance(old_level, int) and isinstance(new_level, int):
            lines.append(f"人口变化 {new_level - old_level:+d}")

        recent = []
        for snap in snapshots[-3:]:
            recent.append(
                f"时间{snap.metrics.get('game_time', '?')} 金币{snap.metrics.get('gold', '?')} "
                f"等级{snap.metrics.get('level', '?')} 建议{snap.advice}"
            )
        lines.append("最近三次分析：" + " | ".join(recent))
        lines.append(f"上一条建议：{latest.advice}")
        return "\n".join(lines)

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
        confidence = bridge_facts.get("confidence", "unknown") if bridge_facts else "none"
        bridge_text = "无视觉核验结果"
        if bridge_facts:
            bridge_text = "，".join(
                f"{key}={bridge_facts.get(key, 'unknown')}"
                for key in (
                    "board_strength",
                    "economy_state",
                    "upgrade_window",
                    "streak_state",
                    "contest_pressure",
                    "positioning_risk",
                    "item_clarity",
                    "focus",
                    "evidence",
                )
            )
        address_line = f"称呼玩家：{payload.address}" if payload.address else "称呼玩家：不要强行称呼"
        return (
            f"{system_prompt}\n\n"
            "决策规则：\n"
            "1. 优先相信云顶硬数据和经济信息，其次参考视觉核验。\n"
            "2. 如果视觉 confidence 不是 high，不要猜测具体羁绊、装备归属或站位细节。\n"
            "3. 优先给高收益运营建议，例如保血、升人口、搜牌、存钱。\n"
            "4. 只输出一句中文建议，不超过50字，不要解释，不要分点。\n"
            "5. 如果上一条建议仍然有效，可以更明确，但不要机械重复。\n\n"
            f"{address_line}\n"
            f"当前云顶摘要：{payload.game_summary or '无'}\n"
            f"当前关键数值：时间{payload.metrics.get('game_time', '?')} 金币{payload.metrics.get('gold', '?')} "
            f"等级{payload.metrics.get('level', '?')} 事件{payload.metrics.get('event_signature', 'none')}\n"
            f"规则引擎提示：{rule_hint or '无'}\n"
            f"视觉核验置信度：{confidence}\n"
            f"视觉核验结果：{bridge_text}\n"
            f"短时历史：\n{self.build_history_context(snapshots)}"
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
        if name in seen:
            continue
        seen.add(name)
        hp = int(player.get("championStats", {}).get("currentHealth", 0) or 0)
        if hp > 0:
            alive += 1
    return alive


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
