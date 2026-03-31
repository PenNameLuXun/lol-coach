from __future__ import annotations

from dataclasses import dataclass

from src.game_plugins import build_default_registry
from src.game_plugins.base import GamePlugin, GameState, RuleResult


@dataclass(slots=True)
class ActiveGameContext:
    plugin: GamePlugin
    state: GameState


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

    def discover_active_context(self) -> ActiveGameContext | None:
        for plugin in self._registry.all():
            if not plugin.is_available():
                continue
            raw_data = plugin.fetch_live_data()
            if raw_data is None:
                continue
            if not plugin.detect(raw_data, {}):
                continue
            state = plugin.extract_state(raw_data, {})
            return ActiveGameContext(plugin=plugin, state=state)
        return None

    def had_seen_activity(self) -> bool:
        return any(plugin.has_seen_activity() for plugin in self._registry.all())

    def evaluate_context(self, context: ActiveGameContext) -> RuleAdvice | None:
        candidates = context.plugin.evaluate_rules(context.state)
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item.priority)
        return RuleAdvice(
            text=context.plugin.render_advice(best, context.state),
            priority=best.priority,
            rule_id=best.rule_id,
            game_type=context.state.game_type,
            plugin_id=context.plugin.id,
            state=context.state,
            rule=best,
            plugin=context.plugin,
        )

    def evaluate(self, live_data: dict | None, metrics: dict[str, int | str]) -> RuleAdvice | None:
        if not live_data:
            return None
        plugin = self._registry.detect(live_data, metrics)
        if plugin is None:
            return None
        state = plugin.extract_state(live_data, metrics)
        return self.evaluate_context(ActiveGameContext(plugin=plugin, state=state))
