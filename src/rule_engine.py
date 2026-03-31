from __future__ import annotations

from dataclasses import dataclass

from src.game_plugins import build_default_registry
from src.game_plugins.base import GamePlugin, GameState, RuleResult


@dataclass(slots=True)
class RuleAdvice:
    text: str
    priority: int
    rule_id: str
    game_type: str
    plugin_id: str
    state: GameState
    rule: RuleResult
    plugin: GamePlugin


class RuleEngine:
    """Thin wrapper over the plugin registry to produce the best rule advice."""

    def __init__(self, enabled_plugin_ids: list[str] | None = None):
        self._registry = build_default_registry(enabled_plugin_ids=enabled_plugin_ids)

    @property
    def registry(self):
        return self._registry

    def evaluate(self, live_data: dict | None, metrics: dict[str, int | str]) -> RuleAdvice | None:
        if not live_data:
            return None
        plugin = self._registry.detect(live_data, metrics)
        if plugin is None:
            return None
        state = plugin.extract_state(live_data, metrics)
        candidates = plugin.evaluate_rules(state)
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item.priority)
        return RuleAdvice(
            text=plugin.render_advice(best, state),
            priority=best.priority,
            rule_id=best.rule_id,
            game_type=state.game_type,
            plugin_id=plugin.id,
            state=state,
            rule=best,
            plugin=plugin,
        )
