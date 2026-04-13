from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

from src.game_plugins import build_default_registry
from src.game_plugins.base import GamePlugin, GameState, RuleResult


class EngineState(str, Enum):
    DISCOVERING = "discovering"
    BOUND = "bound"


@dataclass(slots=True)
class ActiveGameContext:
    plugin: GamePlugin
    state: GameState


@dataclass(slots=True)
class RuleAdvice:
    text: str
    hint: str
    priority: int
    rule_id: str
    game_type: str
    plugin_id: str
    state: GameState
    rule: RuleResult
    plugin: GamePlugin
    selected_rules: tuple[RuleResult, ...] = ()


class RuleEngine:
    """Thin wrapper over the plugin registry to produce the best rule advice."""

    def __init__(self, enabled_plugin_ids: list[str] | None = None, config=None):
        self._registry = build_default_registry(enabled_plugin_ids=enabled_plugin_ids, config=config)
        self._state = EngineState.DISCOVERING
        self._bound_plugin_id: str | None = None

    @property
    def registry(self):
        return self._registry

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def bound_plugin_id(self) -> str | None:
        return self._bound_plugin_id

    def discover_active_context(self) -> ActiveGameContext | None:
        if self._state == EngineState.BOUND and self._bound_plugin_id:
            plugin = self._registry.get(self._bound_plugin_id)
            context = self._build_context_for_plugin(plugin)
            if context is not None:
                return context
            self.invalidate_binding()

        for plugin in self._registry.all():
            context = self._build_context_for_plugin(plugin)
            if context is not None:
                self.bind_plugin(plugin.id)
                return context
        return None

    def had_seen_activity(self) -> bool:
        if self._bound_plugin_id:
            plugin = self._registry.get(self._bound_plugin_id)
            return bool(plugin and plugin.has_seen_activity())
        return any(plugin.has_seen_activity() for plugin in self._registry.all())

    def bind_plugin(self, plugin_id: str):
        self._bound_plugin_id = plugin_id
        self._state = EngineState.BOUND

    def invalidate_binding(self):
        self._bound_plugin_id = None
        self._state = EngineState.DISCOVERING

    def evaluate_context(self, context: ActiveGameContext) -> RuleAdvice | None:
        candidates = context.plugin.evaluate_rules(context.state)
        if not candidates:
            return None
        selected = _select_by_category(candidates)
        best = selected[0]  # highest priority overall
        # Combine messages from different categories
        if len(selected) > 1:
            combined_text = "；".join(r.message for r in selected)
        else:
            combined_text = best.message
        return RuleAdvice(
            text=combined_text,
            hint=context.plugin.build_rule_hint(best, context.state),
            priority=best.priority,
            rule_id=best.rule_id,
            game_type=context.state.game_type,
            plugin_id=context.plugin.id,
            state=context.state,
            rule=best,
            plugin=context.plugin,
            selected_rules=tuple(selected),
        )

    def evaluate(self, live_data: dict | None, metrics: dict[str, int | str]) -> RuleAdvice | None:
        if not live_data:
            return None
        plugin = self._registry.detect(live_data, metrics)
        if plugin is None:
            return None
        state = plugin.extract_state(live_data, metrics)
        return self.evaluate_context(ActiveGameContext(plugin=plugin, state=state))

    def _build_context_for_plugin(self, plugin: GamePlugin | None) -> ActiveGameContext | None:
        if plugin is None or not plugin.is_available():
            return None
        raw_data = plugin.fetch_live_data()
        if raw_data is None:
            return None
        if not plugin.detect(raw_data, {}):
            return None
        state = plugin.extract_state(raw_data, {})
        return ActiveGameContext(plugin=plugin, state=state)


def _select_by_category(candidates: list[RuleResult]) -> list[RuleResult]:
    """Pick the highest-priority rule from each tag category.

    The "category" of a rule is its first tag (e.g. ``powerspike``,
    ``economy``).  Rules without tags fall into a shared ``_default``
    category.  Returns results sorted by descending priority.
    """
    best_per_cat: dict[str, RuleResult] = {}
    for rule in candidates:
        cat = rule.tags[0] if rule.tags else "_default"
        existing = best_per_cat.get(cat)
        if existing is None or rule.priority > existing.priority:
            best_per_cat[cat] = rule
    return sorted(best_per_cat.values(), key=lambda r: r.priority, reverse=True)
