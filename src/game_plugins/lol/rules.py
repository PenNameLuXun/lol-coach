from __future__ import annotations

from src.game_plugins.base import GameState, RuleResult


def evaluate_lol_rules(state: GameState) -> list[RuleResult]:
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

    if is_dead:
        rules.append(RuleResult("lol_dead_reset", 98, "你已阵亡，先看小地图，复活后跟队友一起出门。", ("reset",)))

    if not is_dead:
        if hp_pct <= 20 and gold >= 1300:
            rules.append(RuleResult("lol_low_hp_recall_spend", 95, "残血且钱够，立刻回城补关键装，别继续贪线。", ("recall", "economy")))
        elif hp_pct <= 20:
            rules.append(RuleResult("lol_low_hp_retreat", 93, "血量极低，立刻撤到安全位置，不要贪任何东西。", ("retreat",)))
        elif hp_pct <= 35 and mana_pct <= 20:
            rules.append(RuleResult("lol_low_resources_reset", 90, "血蓝双低，先回城重置状态，再考虑接下一波。", ("reset",)))
        elif hp_pct <= 35:
            rules.append(RuleResult("lol_low_hp_safe", 85, "血量偏低，远离敌方视野，避免接受正面交战。", ("retreat",)))

    if not is_dead and mana_pct <= 15 and hp_pct >= 50:
        rules.append(RuleResult("lol_oom_warning", 78, "蓝量几乎耗尽，无法发动技能，避免接战或回城补蓝。", ("reset",)))

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

    if gold >= 2500 and hp_pct >= 40 and not is_dead:
        rules.append(RuleResult("lol_gold_overflow", 88, "金币严重积压超2500，立刻找时机回城，金币放着是浪费。", ("economy", "recall")))
    elif gold >= 1800 and hp_pct >= 35 and not is_dead:
        rules.append(RuleResult("lol_spend_gold", 72, "你身上金币很多，找安全时间窗回城更新装备。", ("economy", "recall")))
    elif gold >= 1300 and hp_pct <= 50 and not is_dead:
        rules.append(RuleResult("lol_hurt_and_rich_recall", 80, "血量偏低且攒了不少金币，这是个好时机回城。", ("economy", "recall")))

    if level <= 5 and game_minutes >= 10:
        rules.append(RuleResult("lol_low_level_xp", 76, "等级偏低，优先刷线/野区补经验，不要轻易参与混乱团战。", ("farm",)))
    if level >= 16 and hp_pct >= 60 and gold <= 500:
        rules.append(RuleResult("lol_full_build_fight", 65, "等级较高且装备接近完整，可以主动寻找有利交战机会。", ("fight",)))

    if game_minutes <= 14 and cs < game_minutes * 6 and not is_dead:
        rules.append(RuleResult("lol_cs_behind", 70, f"前期补刀偏少（{cs}刀），专注清线，减少无效走动。", ("farm",)))
    if game_minutes >= 25 and cs < game_minutes * 5:
        rules.append(RuleResult("lol_late_cs_low", 62, "后期补刀仍不足，清兵线依然是被动期最稳的选择。", ("farm",)))

    if game_minutes == 5 and not is_dead:
        rules.append(RuleResult("lol_early_first_back", 55, "游戏5分钟，注意首次回城时机，买核心小件再回线。", ("economy",)))
    if game_minutes >= 20 and game_minutes <= 22 and ally_dead == 0 and enemy_dead == 0:
        rules.append(RuleResult("lol_mid_game_group", 60, "中期到来，适时与队友集合，避免单人在野区被针对。", ("rotate",)))

    if position == "JUNGLE" and not is_dead and game_minutes >= 3 and game_minutes % 5 == 0:
        rules.append(RuleResult("lol_jungle_objective_timer", 68, "野区资源刷新节点，提前绕路预判龙/先锋/大龙位置。", ("objective",)))
    if position == "UTILITY" and ally_dead == 0 and hp_pct >= 50 and not is_dead:
        rules.append(RuleResult("lol_support_vision", 45, "辅助多插眼控制视野，尤其是龙坑和大龙附近。", ("vision",)))

    if event_sig == "none" and hp_pct >= 70 and mana_pct >= 50 and enemy_dead == 0 and ally_dead == 0:
        rules.append(RuleResult("lol_stable_farm", 40, "局势平稳，优先补刀控线，等下一次资源刷新。", ("farm", "tempo")))

    # ── Dragon awareness ───────────────────────────────────────
    dragon_count = _int(metrics.get("dragon_count"))
    if latest_event == "DragonKill" and dragon_count >= 3 and hp_pct >= 40 and not is_dead:
        rules.append(RuleResult("lol_dragon_soul_incoming", 92, "已击杀3条龙，下条龙就是龙魂！全队务必争夺。", ("objective", "dragon")))

    # ── Ward / vision awareness ────────────────────────────────
    ward_score = _int(metrics.get("ward_score"))
    if ward_score <= 5 and game_minutes >= 15 and not is_dead:
        rules.append(RuleResult("lol_low_vision", 58, "视野分数太低，记得买控制守卫，关键位置插眼。", ("vision",)))

    # ── KDA-based rules ────────────────────────────────────────
    kills = _int(metrics.get("kills"))
    deaths = _int(metrics.get("deaths"))
    assists = _int(metrics.get("assists"))

    if deaths >= 5 and game_minutes <= 20 and not is_dead:
        rules.append(RuleResult("lol_high_deaths_warning", 86, "死亡次数过多，一定不要单独行动，跟着队友走。", ("positioning", "recovery")))

    if kills + assists >= 8 and deaths <= 2 and hp_pct >= 50 and not is_dead:
        rules.append(RuleResult("lol_carrying_protect", 74, "你在carry全队，保护好自己比多一次击杀更重要。", ("positioning", "carry")))

    # ── Item count awareness ───────────────────────────────────
    item_count = _int(metrics.get("item_count"))
    if item_count == 0 and game_minutes >= 8 and gold >= 1000 and not is_dead:
        rules.append(RuleResult("lol_no_items_recall", 85, "身上没有装备但有钱，赶紧回城买装。", ("economy", "recall")))

    return rules


def build_lol_rule_hint(rule: RuleResult, state: GameState) -> str:
    return (
        f"{rule.message} 规则观察：最近事件{state.derived.get('latest_event', 'none')}，"
        f"我方阵亡{state.derived.get('ally_dead', 0)}人，"
        f"敌方阵亡{state.derived.get('enemy_dead', 0)}人。"
    )


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
