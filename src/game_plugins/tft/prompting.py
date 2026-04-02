from __future__ import annotations

from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.base import AiPayload


def build_tft_vision_prompt(payload: AiPayload) -> str:
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


def build_tft_history_context(snapshots: list[AnalysisSnapshot]) -> str:
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


def build_tft_decision_prompt(
    system_prompt: str,
    payload: AiPayload,
    bridge_facts: dict[str, str] | None,
    snapshots: list[AnalysisSnapshot],
    rule_hint: str | None = None,
) -> str:
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
        f"短时历史：\n{build_tft_history_context(snapshots)}"
    )


def render_shop_units(entries: list[dict]) -> str:
    units = []
    for entry in entries[:5]:
        name = str(entry.get("name", "") or entry.get("championName", "")).strip()
        cost = entry.get("cost")
        if not name:
            continue
        units.append(f"{name}({cost})" if cost is not None else name)
    return " | ".join(units) if units else "未知"


def render_traits(entries: list[dict]) -> str:
    traits = []
    for entry in entries[:6]:
        name = str(entry.get("name", "")).strip()
        tier = entry.get("tier_current")
        if not name:
            continue
        traits.append(f"{name}{tier}" if tier is not None else name)
    return " | ".join(traits) if traits else "未知"
