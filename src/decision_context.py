from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime


BRIDGE_FIELDS = (
    "scene",
    "fight_state",
    "player_risk",
    "visible_enemies",
    "objective_pressure",
    "wave_state",
    "confidence",
    "focus",
    "evidence",
)


@dataclass(slots=True)
class AnalysisSnapshot:
    timestamp: datetime
    game_summary: str
    address: str | None
    metrics: dict[str, int | str]
    bridge_facts: dict[str, str]
    advice: str


@dataclass(slots=True)
class ContextWindow:
    limit: int = 5
    _items: deque[AnalysisSnapshot] = field(default_factory=deque)

    def __post_init__(self):
        self._items = deque(maxlen=self.limit)

    def add(self, snapshot: AnalysisSnapshot):
        self._items.append(snapshot)

    def empty(self) -> bool:
        return not self._items

    def render_for_prompt(self) -> str:
        if not self._items:
            return "无历史上下文。"

        items = list(self._items)
        oldest = items[0]
        latest = items[-1]
        lines: list[str] = []

        gold_delta = _safe_delta(oldest.metrics.get("gold"), latest.metrics.get("gold"))
        level_delta = _safe_delta(oldest.metrics.get("level"), latest.metrics.get("level"))
        cs_delta = _safe_delta(oldest.metrics.get("cs"), latest.metrics.get("cs"))
        if gold_delta is not None or level_delta is not None or cs_delta is not None:
            parts = []
            if gold_delta is not None:
                parts.append(f"金币变化 {gold_delta:+d}")
            if level_delta is not None:
                parts.append(f"等级变化 {level_delta:+d}")
            if cs_delta is not None:
                parts.append(f"补刀变化 {cs_delta:+d}")
            lines.append("趋势：" + "，".join(parts))

        risk_counter = Counter(
            snap.bridge_facts.get("player_risk", "unknown")
            for snap in items
            if snap.bridge_facts.get("player_risk")
        )
        if risk_counter:
            lines.append(f"最近风险分布：{_top_counter(risk_counter)}")

        scene_counter = Counter(
            snap.bridge_facts.get("scene", "unknown")
            for snap in items
            if snap.bridge_facts.get("scene")
        )
        if scene_counter:
            lines.append(f"最近场景分布：{_top_counter(scene_counter)}")

        last_three = items[-3:]
        snapshot_lines = []
        for idx, snap in enumerate(last_three, start=1):
            metrics = snap.metrics
            bridge = snap.bridge_facts
            snapshot_lines.append(
                f"T-{len(last_three) - idx}: 时间{metrics.get('game_time', '?')} 金币{metrics.get('gold', '?')} "
                f"血量{metrics.get('hp_pct', '?')}% 风险{bridge.get('player_risk', 'unknown')} "
                f"场景{bridge.get('scene', 'unknown')} 建议{snap.advice}"
            )
        lines.append("最近三次分析：" + " | ".join(snapshot_lines))
        lines.append(f"上一条建议：{latest.advice}")
        return "\n".join(lines)


def build_bridge_prompt(game_summary: str, metrics: dict[str, int | str]) -> str:
    return (
        "你是视觉核验模块，只做高置信事实提取，不做长解释。\n"
        "请结合这张LOL截图与已知游戏摘要，输出严格的键值对，每行一个字段，不要额外发挥。\n"
        "字段必须完整输出：\n"
        "scene: lane|river|jungle|base|objective|teamfight|unknown\n"
        "fight_state: none|skirmish|teamfight|postfight|unknown\n"
        "player_risk: low|medium|high|unknown\n"
        "visible_enemies: 0|1|2|3|4|5|unknown\n"
        "objective_pressure: none|dragon|baron|herald|tower|base|unknown\n"
        "wave_state: pushing|neutral|under_tower|crashing|unknown\n"
        "confidence: high|medium|low\n"
        "focus: 用不超过12字写出当前镜头最值得关注的点\n"
        "evidence: 用不超过24字列出你最确信的视觉依据\n\n"
        f"已知摘要：{game_summary or '无'}\n"
        f"关键数值：时间{metrics.get('game_time', '?')} 金币{metrics.get('gold', '?')} "
        f"血量{metrics.get('hp_pct', '?')}% 等级{metrics.get('level', '?')}\n"
        "如果截图看不清，请把相关字段写 unknown，并把 confidence 降低。"
    )


def parse_bridge_output(text: str) -> dict[str, str]:
    result = {field: "unknown" for field in BRIDGE_FIELDS}
    result["raw"] = text.strip()
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if ":" in cleaned:
            key, value = cleaned.split(":", 1)
        elif "：" in cleaned:
            key, value = cleaned.split("：", 1)
        else:
            continue
        key = key.strip().lower()
        if key in result:
            result[key] = value.strip() or "unknown"
    if result["confidence"] == "unknown":
        lowered = text.lower()
        for label in ("high", "medium", "low"):
            if f"confidence {label}" in lowered or f"confidence:{label}" in lowered:
                result["confidence"] = label
                break
    return result


def build_decision_prompt(
    system_prompt: str,
    game_summary: str,
    address: str | None,
    metrics: dict[str, int | str],
    bridge_facts: dict[str, str] | None,
    historical_context: str,
) -> str:
    address_line = f"称呼玩家：{address}" if address else "称呼玩家：不要强行称呼"
    bridge_text = _bridge_facts_to_text(bridge_facts)
    confidence = bridge_facts.get("confidence", "unknown") if bridge_facts else "none"
    safety_policy = (
        "决策规则：\n"
        "1. 优先相信LoL客户端硬数据，其次相信视觉核验高置信字段。\n"
        "2. 如果视觉 confidence 不是 high，禁止根据截图猜测技能CD、草丛埋伏或地图外信息。\n"
        "3. 如果证据不足，给保守且高收益的宏观建议，例如回城、控线、补眼、等关键资源。\n"
        "4. 只输出一句中文建议，不超过50字，不要解释，不要分点。\n"
        "5. 如果上一条建议仍然有效，允许给出更明确的执行版本，但不要机械重复原句。"
    )
    return (
        f"{system_prompt}\n\n"
        f"{safety_policy}\n\n"
        f"{address_line}\n"
        f"当前游戏摘要：{game_summary or '无'}\n"
        f"当前关键数值：时间{metrics.get('game_time', '?')} 金币{metrics.get('gold', '?')} "
        f"血量{metrics.get('hp_pct', '?')}% 蓝量{metrics.get('mana_pct', '?')}% "
        f"等级{metrics.get('level', '?')} KDA{metrics.get('kda', '?')} 补刀{metrics.get('cs', '?')}\n"
        f"视觉核验置信度：{confidence}\n"
        f"视觉核验结果：{bridge_text}\n"
        f"短时历史：\n{historical_context}"
    )


def _bridge_facts_to_text(bridge_facts: dict[str, str] | None) -> str:
    if not bridge_facts:
        return "无视觉核验结果"
    parts = []
    for field in BRIDGE_FIELDS:
        value = bridge_facts.get(field, "unknown")
        parts.append(f"{field}={value}")
    return "，".join(parts)


def _safe_delta(old: int | str | None, new: int | str | None) -> int | None:
    if not isinstance(old, int) or not isinstance(new, int):
        return None
    return new - old


def _top_counter(counter: Counter[str]) -> str:
    return "，".join(f"{name}:{count}" for name, count in counter.most_common(3))
