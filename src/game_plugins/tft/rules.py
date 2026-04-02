from __future__ import annotations

from src.game_plugins.base import GameState, RuleResult


def evaluate_tft_rules(state: GameState) -> list[RuleResult]:
    hp = _int(state.derived.get("player_hp"))
    level = _int(state.derived.get("level"))
    alive = _int(state.derived.get("alive_players"))
    game_time_seconds = _int(state.metrics.get("game_time_seconds"))
    game_minutes = game_time_seconds // 60

    rules: list[RuleResult] = []

    if hp <= 15:
        rules.append(RuleResult("tft_critical_hp", 99, f"血量仅剩{hp}，必须全力D牌提战力，经济已无意义。", ("roll", "survival")))
    elif hp <= 25:
        rules.append(RuleResult("tft_low_hp_roll", 96, f"血量{hp}危险，立刻搜牌保血，别再贪经济。", ("roll", "survival")))
    elif hp <= 35:
        rules.append(RuleResult("tft_warn_hp_roll", 90, f"血量{hp}偏低，考虑搜牌稳住阵容，避免再被打崩。", ("roll", "survival")))
    elif hp <= 45:
        rules.append(RuleResult("tft_convert_econ", 85, f"血量{hp}开始吃紧，适时转化经济提升战力，先保血。", ("survival",)))

    if level <= 4 and game_minutes >= 6 and hp >= 60:
        rules.append(RuleResult("tft_level_up_5", 70, "可以考虑升到5级，解锁更多棋子槽位。", ("level", "tempo")))
    if level == 5 and game_minutes >= 9 and hp >= 55:
        rules.append(RuleResult("tft_level_up_6", 72, "已5级，时机合适升6级提升出2费棋的概率。", ("level", "tempo")))
    if level == 6 and game_minutes >= 14 and hp >= 50:
        rules.append(RuleResult("tft_level_up_7", 74, "已6级，升7级可提升出3费棋的概率。", ("level", "tempo")))
    if level == 7 and game_minutes >= 20 and hp >= 40:
        rules.append(RuleResult("tft_level_up_8", 78, "进入后期，升8级能大幅提升出4费棋的概率。", ("level", "top4")))
    if level >= 8 and game_minutes >= 26 and hp >= 30 and 0 < alive <= 4:
        rules.append(RuleResult("tft_level_9_push", 72, "决赛圈且8级，可以考虑冲9级出5费棋。", ("level", "top4")))

    if 0 < alive <= 4:
        rules.append(RuleResult("tft_top4_push", 80, f"已进决赛圈（剩{alive}人），开始优化阵容站位保血。", ("top4", "tempo")))
    if 0 < alive <= 3 and hp <= 30:
        rules.append(RuleResult("tft_final_all_in", 95, "决赛圈且血量危急，放手一搏全力D牌，争取吃鸡。", ("roll", "survival", "top4")))
    if 0 < alive <= 2:
        rules.append(RuleResult("tft_final_fight", 97, "最终对决！全力优化站位和阵容，每一格都很关键。", ("top4", "positioning")))

    if game_minutes <= 4 and level <= 3:
        rules.append(RuleResult("tft_early_econ", 50, "对局初期，优先建立经济，不要轻易花钱升级。", ("economy",)))
    if 9 <= game_minutes <= 11 and level <= 5:
        rules.append(RuleResult("tft_stage3_transition", 60, "进入第三阶段，注意阵容方向，开始朝核心羁绊靠拢。", ("tempo",)))
    if game_minutes >= 20 and level <= 6:
        rules.append(RuleResult("tft_late_level_warn", 75, "后期人口偏低，抓紧升级或调整策略，别落后太多。", ("level", "tempo")))

    return rules


def build_tft_rule_hint(rule: RuleResult, state: GameState) -> str:
    return (
        f"{rule.message} 规则观察：当前生命{state.derived.get('player_hp', '?')}，"
        f"存活玩家{state.derived.get('alive_players', '?')}，"
        f"金币{state.derived.get('gold', '?')}。"
    )


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
