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

# ── Item ID → English keyword mapping ────────────────────────────────────────
# Keys: LoL item IDs (language-independent).
# Values: lowercase English strings used in YAML `contains`/`not_contains` checks.
# A single item can produce multiple keywords (space-separated) so existing rule
# patterns like `contains boots` and `contains greaves` both work.
_ITEM_ID_KEYWORDS: dict[int, str] = {
    # ── Marksman Mythics ──────────────────────────────────────────
    3031: "infinity edge",
    6671: "galeforce",
    6672: "kraken slayer",
    6673: "immortal shieldbow shieldbow",
    6675: "navori flickerblade",
    # ── Marksman Legendaries ─────────────────────────────────────
    3046: "phantom dancer",
    3085: "runaan's hurricane hurricane",
    3036: "lord dominik's regards lord dominik",
    3033: "mortal reminder",
    3072: "bloodthirster",
    3094: "rapid firecannon",
    3095: "stormrazor",
    3139: "mercurial scimitar",
    3508: "essence reaver",
    # ── Assassin / Fighter ───────────────────────────────────────
    3153: "blade of the ruined king ruined king botrk",
    6697: "hubris",
    6676: "the collector collector",
    6694: "serrated dirk",
    3142: "youmuu's ghostblade ghostblade",
    3179: "umbral glaive",
    6695: "serpent's fang",
    3814: "edge of night",
    # ── Fighter Mythics ──────────────────────────────────────────
    6631: "stridebreaker",
    6632: "divine sunderer",
    6633: "trinity force",
    6630: "goredrinker",
    # ── Tank / Support ────────────────────────────────────────────
    3068: "sunfire aegis",
    6664: "turbo chemtank",
    3083: "warmog's armor",
    3107: "redemption",
    4005: "imperial mandate",
    # ── Mage ─────────────────────────────────────────────────────
    3089: "rabadon's deathcap",
    3135: "void staff",
    3165: "morellonomicon",
    4646: "night harvester",
    4637: "riftmaker",
    6653: "liandry's anguish",
    6655: "luden's tempest",
    6656: "everfrost",
    # ── Boots — each includes "boots" so `not_contains boots` works ──
    1001: "basic boots boots",
    3006: "berserker's greaves greaves boots",
    3047: "plated steelcaps steelcaps boots",
    3111: "mercury's treads treads boots",
    3020: "sorcerer's shoes boots",
    3158: "ionian boots of lucidity boots",
    3009: "boots of swiftness boots",
    # ── Components ───────────────────────────────────────────────
    1038: "b.f. sword",
    1043: "recurve bow",
    3086: "zeal",
    1018: "cloak of agility",
    3134: "long sword",       # actually 3134 is Serrated Dirk... 1036 is Long Sword
    1036: "long sword",
    1037: "pickaxe",
    3035: "last whisper",
    # ── Jungle / Support consumables (commonly seen in item slot) ─
    3340: "stealth ward totem",
    3364: "oracle lens",
    3363: "farsight alteration",
    2055: "control ward",
}


def _build_items_lower(items_str: str, item_ids_str: str) -> str:
    """Translate item IDs to English keywords; fall back to original display names."""
    parts: list[str] = []
    # Translate via item IDs first (most reliable, language-agnostic)
    if item_ids_str:
        for id_tok in item_ids_str.split("|"):
            try:
                iid = int(id_tok)
            except ValueError:
                continue
            kw = _ITEM_ID_KEYWORDS.get(iid)
            if kw:
                parts.append(kw)
            else:
                # Unknown ID: keep numeric so rules can still match by ID if needed
                parts.append(str(iid))
    # Also append lowercased display names for any items whose IDs were missing
    # or for future rules that prefer display name matching
    if items_str:
        for name in items_str.split("|"):
            n = name.strip().lower()
            if n:
                parts.append(n)
    return " | ".join(parts)


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
    # items string → English keywords for "contains" checks (language-agnostic via item IDs)
    ctx["items_lower"] = _build_items_lower(
        str(ctx.get("items", "")),
        str(ctx.get("item_ids", "")),
    )
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
