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

        rules: list[RuleResult] = []
        if hp <= 25 and gold >= 20:
            rules.append(RuleResult("tft_low_hp_roll", 96, "血量危险，别再贪利息，立刻搜牌保血。", ("roll", "survival")))
        if hp <= 40 and gold >= 50:
            rules.append(RuleResult("tft_convert_econ", 88, "血量开始危险，把50金的一部分转成战力，先保血。", ("economy", "survival")))
        if gold >= 50 and hp >= 45:
            rules.append(RuleResult("tft_hold_interest", 74, "经济健康，继续吃满50利息，别急着乱D。", ("economy",)))
        if alive <= 4 and gold >= 30:
            rules.append(RuleResult("tft_top4_push", 82, "已进决赛圈，别再纯贪经济，开始保血提质量。", ("top4", "tempo")))
        if level <= 6 and gold <= 10 and hp >= 60:
            rules.append(RuleResult("tft_rebuild_econ", 64, "经济偏薄，先稳住节奏，别在弱势回合硬搜。", ("economy", "tempo")))
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
