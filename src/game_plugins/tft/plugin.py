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
        ow = raw_data.get("_overwolf")  # injected by TftLiveDataSource when Overwolf connected

        if ow:
            # Overwolf provides accurate real-time TFT data
            hp = int(ow.get("hp", 100))
            gold = int(ow.get("gold", 0))
            level = int(ow.get("level", 1))
            alive = int(ow.get("alive_players", 0))
            source = "overwolf"
        else:
            # Fallback: Riot Live Client (limited TFT support)
            hp = _find_tft_hp(raw_data, active.get("summonerName", ""))
            alive = _count_tft_alive(raw_data)
            raw_gold = int(active.get("currentGold", 0) or 0)
            gold = raw_gold if raw_gold <= 100 else 0  # currentGold is cumulative in TFT
            level = int(active.get("level", 1) or 1)
            source = "riot"

        print(f"[TFT state:{source}] hp={hp} gold={gold} level={level} alive={alive}")

        derived = {
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
        }
        return GameState(plugin_id=self.id, game_type="tft", raw_data=raw_data, metrics=metrics, derived=derived)

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        hp = _int(state.derived.get("player_hp"))
        level = _int(state.derived.get("level"))
        alive = _int(state.derived.get("alive_players"))
        game_time_seconds = _int(state.metrics.get("game_time_seconds"))
        game_minutes = game_time_seconds // 60

        rules: list[RuleResult] = []

        # ── 血量危机（gold 数据不可靠，仅依赖 hp）────────────────────────
        if hp <= 15:
            rules.append(RuleResult("tft_critical_hp", 99, f"血量仅剩{hp}，必须全力D牌提战力，经济已无意义。", ("roll", "survival")))
        elif hp <= 25:
            rules.append(RuleResult("tft_low_hp_roll", 96, f"血量{hp}危险，立刻搜牌保血，别再贪经济。", ("roll", "survival")))
        elif hp <= 35:
            rules.append(RuleResult("tft_warn_hp_roll", 90, f"血量{hp}偏低，考虑搜牌稳住阵容，避免再被打崩。", ("roll", "survival")))
        elif hp <= 45:
            rules.append(RuleResult("tft_convert_econ", 85, f"血量{hp}开始吃紧，适时转化经济提升战力，先保血。", ("survival",)))

        # ── 升级人口时机（仅依赖 level + game_minutes + hp）──────────────
        if level <= 4 and game_minutes >= 6 and hp >= 60:
            rules.append(RuleResult("tft_level_up_5", 70, "可以考虑升到5级，解锁更多棋子槽位。", ("level", "tempo")))
        if level == 5 and game_minutes >= 9 and hp >= 55:
            rules.append(RuleResult("tft_level_up_6", 72, "已5级，时机合适升6级提升出2费棋的概率。", ("level", "tempo")))
        if level == 6 and game_minutes >= 14 and hp >= 50:
            rules.append(RuleResult("tft_level_up_7", 74, "已6级，升7级可提升出3费棋的概率。", ("level", "tempo")))
        if level == 7 and game_minutes >= 20 and hp >= 40:
            rules.append(RuleResult("tft_level_up_8", 78, "进入后期，升8级能大幅提升出4费棋的概率。", ("level", "top4")))
        if level >= 8 and game_minutes >= 26 and hp >= 30 and alive > 0 and alive <= 4:
            rules.append(RuleResult("tft_level_9_push", 72, "决赛圈且8级，可以考虑冲9级出5费棋。", ("level", "top4")))

        # ── 决赛圈（依赖 alive + hp）─────────────────────────────────────
        if alive > 0 and alive <= 4:
            rules.append(RuleResult("tft_top4_push", 80, f"已进决赛圈（剩{alive}人），开始优化阵容站位保血。", ("top4", "tempo")))
        if alive > 0 and alive <= 3 and hp <= 30:
            rules.append(RuleResult("tft_final_all_in", 95, "决赛圈且血量危急，放手一搏全力D牌，争取吃鸡。", ("roll", "survival", "top4")))
        if alive > 0 and alive <= 2:
            rules.append(RuleResult("tft_final_fight", 97, "最终对决！全力优化站位和阵容，每一格都很关键。", ("top4", "positioning")))

        # ── 阶段节点提示（依赖 game_minutes + level）─────────────────────
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
                summary += f" 商店：{_render_shop_units(state.derived.get('shop', []))}。"
            if state.derived.get("traits"):
                summary += f" 羁绊：{_render_traits(state.derived.get('traits', []))}。"
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
    """Count alive TFT players by unique summonerName with hp > 0.
    Returns 0 when data is unavailable (caller should treat 0 as unknown)."""
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
    # If we got 0 but there are players listed, data hasn't populated yet
    total = len(set(p.get("summonerName", "") for p in data.get("allPlayers", []) if p.get("summonerName")))
    if alive == 0 and total > 0:
        return 0  # signal: data not ready
    return alive


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0


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


def _render_shop_units(entries: list[dict]) -> str:
    units = []
    for entry in entries[:5]:
        name = str(entry.get("name", "") or entry.get("championName", "")).strip()
        cost = entry.get("cost")
        if not name:
            continue
        units.append(f"{name}({cost})" if cost is not None else name)
    return " | ".join(units) if units else "未知"


def _render_traits(entries: list[dict]) -> str:
    traits = []
    for entry in entries[:6]:
        name = str(entry.get("name", "")).strip()
        tier = entry.get("tier_current")
        if not name:
            continue
        traits.append(f"{name}{tier}" if tier is not None else name)
    return " | ".join(traits) if traits else "未知"


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


def _render_shop_units(entries: list[dict]) -> str:
    units = []
    for entry in entries[:5]:
        name = str(entry.get("name", "") or entry.get("championName", "")).strip()
        cost = entry.get("cost")
        if not name:
            continue
        units.append(f"{name}({cost})" if cost is not None else name)
    return " | ".join(units) if units else "未知"


def _render_traits(entries: list[dict]) -> str:
    traits = []
    for entry in entries[:6]:
        name = str(entry.get("name", "")).strip()
        tier = entry.get("tier_current")
        if not name:
            continue
        traits.append(f"{name}{tier}" if tier is not None else name)
    return " | ".join(traits) if traits else "未知"


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


def _render_shop_units(entries: list[dict]) -> str:
    units = []
    for entry in entries[:5]:
        name = str(entry.get("name", "") or entry.get("championName", "")).strip()
        cost = entry.get("cost")
        if not name:
            continue
        units.append(f"{name}({cost})" if cost is not None else name)
    return " | ".join(units) if units else "未知"


def _render_traits(entries: list[dict]) -> str:
    traits = []
    for entry in entries[:6]:
        name = str(entry.get("name", "")).strip()
        tier = entry.get("tier_current")
        if not name:
            continue
        traits.append(f"{name}{tier}" if tier is not None else name)
    return " | ".join(traits) if traits else "未知"
