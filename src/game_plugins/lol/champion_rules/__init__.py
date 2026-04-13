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


def _slugify(name: str) -> str:
    return name.strip().lower().replace("'", "").replace(" ", "")


class ChampionRuleLoader:
    """Loads and evaluates YAML champion rules with hot-reload and cooldown."""

    def __init__(self, rules_dir: Path | str | None = None):
        self._rules_dir = Path(rules_dir) if rules_dir else _RULES_DIR
        self._cache: dict[str, _CachedChampion] = {}
        self._last_fired: dict[str, float] = {}  # rule_id → monotonic timestamp
        # alias slug → yaml file stem（支持中文名/本地化名称反查）
        self._alias_index: dict[str, str] = {}
        self._alias_index_mtime: float = 0.0

    def evaluate(self, champion: str, state: GameState) -> list[RuleResult]:
        """Evaluate champion-specific rules. Returns empty list if no rules file."""
        if not champion:
            return []
        parsed = self._load(champion)
        if parsed is None:
            slug = _slugify(champion)
            resolved = self._alias_index.get(slug, slug)
            logger.info(
                "[ChampionRules] no rules file: champion=%r slug=%r resolved=%r alias_keys=%s",
                champion, slug, resolved,
                sorted(self._alias_index.keys())[:10],
            )
            return []
        ctx = build_context(state)
        now = _time.monotonic()
        results: list[RuleResult] = []
        passed = 0
        for rule_def in parsed.rules:
            when = rule_def.get("when", {})
            if not isinstance(when, dict):
                continue
            if evaluate_when(when, ctx):
                passed += 1
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
        if passed == 0:
            logger.info(
                "[ChampionRules] %s: %d rules loaded, 0 conditions met — ctx=%s",
                champion,
                len(parsed.rules),
                {k: ctx[k] for k in ("level", "game_minutes", "hp_pct", "position", "is_dead") if k in ctx},
            )
        elif results:
            logger.info(
                "[ChampionRules] %s: %d rules ready (passed=%d)",
                champion, len(results), passed,
            )
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

    def _refresh_alias_index(self) -> None:
        """扫描所有 YAML，把 champion 字段和 aliases 列表映射到文件 stem。"""
        try:
            dir_mtime = os.stat(self._rules_dir).st_mtime
        except OSError:
            return
        if dir_mtime == self._alias_index_mtime:
            return
        index: dict[str, str] = {}
        for p in self._rules_dir.glob("*.yaml"):
            if p.stem.startswith("_"):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                continue
            # 文件名本身
            index[_slugify(p.stem)] = p.stem
            # champion 字段（英文正式名）
            champ_field = data.get("champion", "")
            if champ_field:
                index[_slugify(str(champ_field))] = p.stem
            # aliases 列表（可填中文名、别名等）
            for alias in data.get("aliases", []):
                if alias:
                    index[_slugify(str(alias))] = p.stem
        self._alias_index = index
        self._alias_index_mtime = dir_mtime

    def _load(self, champion: str) -> _CachedChampion | None:
        self._refresh_alias_index()
        slug = _slugify(champion)
        # 通过别名索引解析到实际文件 stem
        resolved_stem = self._alias_index.get(slug, slug)
        path = self._rules_dir / f"{resolved_stem}.yaml"
        if not path.is_file():
            logger.info(
                "[ChampionRules] file not found for champion=%r slug=%r resolved=%r path=%s",
                champion, slug, resolved_stem, path,
            )
            return self._cache.get(resolved_stem)

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._cache.get(resolved_stem)

        cached = self._cache.get(resolved_stem)
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
        self._cache[resolved_stem] = entry
        logger.info(
            "[ChampionRules] loaded %s: %d rules from %s",
            champion, len(rules), path.name,
        )
        return entry
