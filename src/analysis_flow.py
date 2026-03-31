from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


BRIDGE_FIELDS = (
    "scene",
    "fight_state",
    "player_risk",
    "threat_level",
    "ally_support",
    "visible_enemies",
    "objective_pressure",
    "resource_window",
    "map_control",
    "engage_window",
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
    reason: str = "scheduled"


@dataclass(slots=True)
class AnalysisPlan:
    should_analyze: bool
    run_bridge: bool
    reason: str


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

    def latest(self) -> AnalysisSnapshot | None:
        return self._items[-1] if self._items else None

    def items(self) -> list[AnalysisSnapshot]:
        return list(self._items)


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


def choose_analysis_plan(
    current_metrics: dict[str, int | str],
    previous_snapshot: AnalysisSnapshot | None,
    has_image: bool,
    now: datetime,
    trigger_cfg: dict[str, int | bool],
) -> AnalysisPlan:
    if previous_snapshot is None:
        return AnalysisPlan(True, has_image, "initial")

    force_after = int(trigger_cfg.get("force_after_seconds", 45))
    hp_drop_threshold = int(trigger_cfg.get("hp_drop_pct", 20))
    gold_delta_threshold = int(trigger_cfg.get("gold_delta", 350))
    cs_delta_threshold = int(trigger_cfg.get("cs_delta", 8))
    stable_skip = bool(trigger_cfg.get("skip_stable_cycles", True))

    elapsed = (now - previous_snapshot.timestamp).total_seconds()
    if elapsed >= force_after:
        return AnalysisPlan(True, has_image, "stale_context")

    prev = previous_snapshot.metrics
    hp_drop = _int_value(prev.get("hp_pct")) - _int_value(current_metrics.get("hp_pct"))
    if hp_drop >= hp_drop_threshold:
        return AnalysisPlan(True, has_image, "hp_drop")

    if _int_value(current_metrics.get("level")) > _int_value(prev.get("level")):
        return AnalysisPlan(True, False, "level_up")

    if _int_value(current_metrics.get("gold")) - _int_value(prev.get("gold")) >= gold_delta_threshold:
        return AnalysisPlan(True, False, "gold_spike")

    if _int_value(current_metrics.get("cs")) - _int_value(prev.get("cs")) >= cs_delta_threshold:
        return AnalysisPlan(True, False, "farm_shift")

    current_events = str(current_metrics.get("event_signature", "none"))
    prev_events = str(prev.get("event_signature", "none"))
    if current_events != prev_events and current_events != "none":
        return AnalysisPlan(True, has_image, "event_change")

    prev_bridge = previous_snapshot.bridge_facts
    if prev_bridge.get("threat_level") in {"critical", "pressured"}:
        return AnalysisPlan(True, has_image, "threat_followup")
    if prev_bridge.get("resource_window") in {"contest_objective", "push_tower"}:
        return AnalysisPlan(True, has_image, "resource_window")
    if prev_bridge.get("objective_pressure") in {"dragon", "baron", "herald"}:
        return AnalysisPlan(True, has_image, "objective_pressure")

    return AnalysisPlan(not stable_skip, False, "stable_skip" if stable_skip else "scheduled")


def _int_value(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
