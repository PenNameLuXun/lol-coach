"""Condition evaluator for YAML-driven champion rules.

Supports simple expressions in the `when` block of each rule:
  - Numeric comparisons: ">= 50", "<= 14", "== 6", "> 1300", "< 30"
  - Boolean: true, false
  - String match: "JUNGLE", "MIDDLE" (exact match, case-insensitive)
  - All conditions in a `when` block are AND-combined.

Available variables come from GameState.metrics + GameState.derived + computed fields.
"""

from __future__ import annotations

import re

from src.game_plugins.base import GameState

# Matches patterns like ">= 50", "< 14", "== 6", "!= 0"
_CMP_PATTERN = re.compile(r"^(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)$")


def build_context(state: GameState) -> dict[str, int | str | bool]:
    """Flatten GameState into a single dict for condition evaluation."""
    ctx: dict[str, int | str | bool] = {}
    ctx.update(state.metrics)
    ctx.update(state.derived)
    # Computed fields
    game_time_seconds = _to_int(ctx.get("game_time_seconds", 0))
    ctx["game_minutes"] = game_time_seconds // 60
    # Normalize string-booleans to real bools
    for key in ("is_dead", "has_flash", "has_tp"):
        val = ctx.get(key)
        if isinstance(val, str):
            ctx[key] = val.lower() == "true"
    # items string → set-like helpers for "contains" checks
    items_str = str(ctx.get("items", ""))
    ctx["items_lower"] = items_str.lower()
    return ctx


def evaluate_when(when: dict, ctx: dict[str, int | str | bool]) -> bool:
    """Evaluate all conditions in a `when` block. Returns True if ALL match.

    A key may map to a single value or a list of values.  When a list is
    given every entry must match (AND), which lets YAML express ranges
    without duplicate keys::

        level:
          - ">= 2"
          - "<= 5"
    """
    for key, expected in when.items():
        actual = ctx.get(key)
        if isinstance(expected, list):
            if not all(_match_condition(actual, e) for e in expected):
                return False
        else:
            if not _match_condition(actual, expected):
                return False
    return True


def _match_condition(actual, expected) -> bool:
    """Match a single condition value against the actual context value."""
    if actual is None:
        return False

    # Boolean expected
    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual == expected
        if isinstance(actual, str):
            return (actual.lower() == "true") == expected
        return bool(actual) == expected

    # Numeric expected (int/float directly in YAML)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return _to_num(actual) == expected

    # String expected — could be a comparison expression, contains, or exact match
    if isinstance(expected, str):
        match = _CMP_PATTERN.match(expected.strip())
        if match:
            op, threshold_str = match.groups()
            threshold = float(threshold_str)
            actual_num = _to_num(actual)
            if actual_num is None:
                return False
            return _compare(actual_num, op, threshold)
        # "contains <value>" — substring check (case-insensitive)
        stripped = expected.strip()
        if stripped.lower().startswith("contains "):
            needle = stripped[9:].strip().lower()
            return needle in str(actual).lower()
        # "not_contains <value>" — negative substring check
        if stripped.lower().startswith("not_contains "):
            needle = stripped[13:].strip().lower()
            return needle not in str(actual).lower()
        # Exact string match (case-insensitive)
        return str(actual).lower() == expected.lower()

    return False


def _compare(actual: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return actual >= threshold
    if op == "<=":
        return actual <= threshold
    if op == "==":
        return actual == threshold
    if op == "!=":
        return actual != threshold
    if op == ">":
        return actual > threshold
    if op == "<":
        return actual < threshold
    return False


def _to_num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_int(value) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0
    return 0
