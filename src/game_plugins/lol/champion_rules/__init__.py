"""Dynamic champion-specific rule loader.

Scans YAML files in this directory, caches parsed rules per champion,
and hot-reloads when files change (mtime check).
"""

from __future__ import annotations

import logging
import os
import time as _time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.game_plugins.base import GameState, RuleResult
from src.game_plugins.lol.champion_rules._schema import build_context, evaluate_when

logger = logging.getLogger("lol_coach.champion_rules")

_RULES_DIR = Path(__file__).parent

# Default cooldown in seconds when a rule doesn't specify one.
_DEFAULT_COOLDOWN = 60


@dataclass(slots=True)
class _CachedChampion:
    """Parsed champion rules + file mtime for cache invalidation."""
    rules: list[dict[str, Any]]
    mtime: float


class ChampionRuleLoader:
    """Loads and evaluates YAML champion rules with hot-reload and cooldown."""

    def __init__(self, rules_dir: Path | str | None = None):
        self._rules_dir = Path(rules_dir) if rules_dir else _RULES_DIR
        self._cache: dict[str, _CachedChampion] = {}
        self._last_fired: dict[str, float] = {}  # rule_id → monotonic timestamp

    def evaluate(self, champion: str, state: GameState) -> list[RuleResult]:
        """Evaluate champion-specific rules. Returns empty list if no rules file."""
        if not champion:
            return []
        parsed = self._load(champion)
        if parsed is None:
            return []
        ctx = build_context(state)
        now = _time.monotonic()
        results: list[RuleResult] = []
        for rule_def in parsed.rules:
            when = rule_def.get("when", {})
            if not isinstance(when, dict):
                continue
            if evaluate_when(when, ctx):
                rule_id = str(rule_def.get("id", ""))
                if not rule_id:
                    continue
                # Cooldown check
                cooldown = float(rule_def.get("cooldown", _DEFAULT_COOLDOWN))
                last = self._last_fired.get(rule_id)
                if last is not None and (now - last) < cooldown:
                    continue
                results.append(RuleResult(
                    rule_id=rule_id,
                    priority=int(rule_def.get("priority", 50)),
                    message=str(rule_def.get("message", "")),
                    tags=tuple(rule_def.get("tags", [])),
                ))
        return results

    def mark_fired(self, rule_ids: list[str]) -> None:
        """Record that these rules were emitted, starting their cooldown."""
        now = _time.monotonic()
        for rid in rule_ids:
            self._last_fired[rid] = now

    def reset_cooldowns(self) -> None:
        """Clear all cooldown state (e.g. on new game)."""
        self._last_fired.clear()

    def available_champions(self) -> list[str]:
        """List champions that have rule files."""
        if not self._rules_dir.is_dir():
            return []
        return sorted(
            p.stem for p in self._rules_dir.glob("*.yaml")
            if not p.stem.startswith("_")
        )

    def _load(self, champion: str) -> _CachedChampion | None:
        slug = champion.strip().lower().replace("'", "").replace(" ", "")
        path = self._rules_dir / f"{slug}.yaml"
        if not path.is_file():
            return self._cache.get(slug)

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._cache.get(slug)

        cached = self._cache.get(slug)
        if cached is not None and cached.mtime == current_mtime:
            return cached

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to load champion rules %s: %s", path, e)
            return cached

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            rules = []

        entry = _CachedChampion(rules=rules, mtime=current_mtime)
        self._cache[slug] = entry
        logger.info(
            "[ChampionRules] loaded %s: %d rules from %s",
            champion, len(rules), path.name,
        )
        return entry
