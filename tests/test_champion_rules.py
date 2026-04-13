"""Tests for the YAML-driven champion rules system."""

import textwrap
from pathlib import Path

import pytest

from src.game_plugins.base import GameState, RuleResult
from src.game_plugins.lol.champion_rules._schema import build_context, evaluate_when
from src.game_plugins.lol.champion_rules import ChampionRuleLoader


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_state(**overrides) -> GameState:
    metrics = {
        "game_type": "lol",
        "game_time_seconds": 600,
        "gold": 1500,
        "level": 6,
        "hp_pct": 75,
        "mana_pct": 50,
        "cs": 80,
        "champion": "Yasuo",
        "position": "MIDDLE",
        "is_dead": "false",
    }
    derived = {
        "ally_dead": 0,
        "enemy_dead": 0,
        "latest_event": "none",
    }
    for k, v in overrides.items():
        if k in derived:
            derived[k] = v
        else:
            metrics[k] = v
    return GameState(
        plugin_id="lol",
        game_type="lol",
        raw_data={},
        metrics=metrics,
        derived=derived,
    )


# ── _schema.py tests ────────────────────────────────────────────────────────

class TestBuildContext:
    def test_merges_metrics_and_derived(self):
        state = _make_state(gold=2000, ally_dead=3)
        ctx = build_context(state)
        assert ctx["gold"] == 2000
        assert ctx["ally_dead"] == 3

    def test_computes_game_minutes(self):
        state = _make_state(game_time_seconds=720)
        ctx = build_context(state)
        assert ctx["game_minutes"] == 12

    def test_normalizes_is_dead_to_bool(self):
        state = _make_state(is_dead="true")
        ctx = build_context(state)
        assert ctx["is_dead"] is True

        state2 = _make_state(is_dead="false")
        ctx2 = build_context(state2)
        assert ctx2["is_dead"] is False


class TestEvaluateWhen:
    def test_numeric_gte(self):
        assert evaluate_when({"gold": ">= 1000"}, {"gold": 1500}) is True
        assert evaluate_when({"gold": ">= 1000"}, {"gold": 999}) is False
        assert evaluate_when({"gold": ">= 1000"}, {"gold": 1000}) is True

    def test_numeric_lte(self):
        assert evaluate_when({"level": "<= 5"}, {"level": 3}) is True
        assert evaluate_when({"level": "<= 5"}, {"level": 6}) is False

    def test_numeric_eq(self):
        assert evaluate_when({"level": "== 6"}, {"level": 6}) is True
        assert evaluate_when({"level": "== 6"}, {"level": 7}) is False

    def test_numeric_gt_lt(self):
        assert evaluate_when({"gold": "> 1000"}, {"gold": 1001}) is True
        assert evaluate_when({"gold": "> 1000"}, {"gold": 1000}) is False
        assert evaluate_when({"hp_pct": "< 30"}, {"hp_pct": 29}) is True
        assert evaluate_when({"hp_pct": "< 30"}, {"hp_pct": 30}) is False

    def test_bool_condition(self):
        assert evaluate_when({"is_dead": False}, {"is_dead": False}) is True
        assert evaluate_when({"is_dead": False}, {"is_dead": True}) is False
        assert evaluate_when({"is_dead": True}, {"is_dead": True}) is True

    def test_string_match(self):
        assert evaluate_when({"position": "JUNGLE"}, {"position": "JUNGLE"}) is True
        assert evaluate_when({"position": "JUNGLE"}, {"position": "MIDDLE"}) is False

    def test_string_match_case_insensitive(self):
        assert evaluate_when({"position": "jungle"}, {"position": "JUNGLE"}) is True

    def test_and_combination(self):
        ctx = {"hp_pct": 25, "gold": 1500, "is_dead": False}
        assert evaluate_when({"hp_pct": "<= 30", "gold": ">= 1300", "is_dead": False}, ctx) is True

    def test_and_fails_if_any_false(self):
        ctx = {"hp_pct": 50, "gold": 1500, "is_dead": False}
        assert evaluate_when({"hp_pct": "<= 30", "gold": ">= 1300"}, ctx) is False

    def test_missing_key_returns_false(self):
        assert evaluate_when({"nonexistent": ">= 5"}, {}) is False

    def test_empty_when_always_matches(self):
        assert evaluate_when({}, {"anything": 42}) is True

    def test_list_range_condition(self):
        """List values express AND — useful for ranges without YAML duplicate keys."""
        assert evaluate_when({"level": [">= 2", "<= 5"]}, {"level": 3}) is True
        assert evaluate_when({"level": [">= 2", "<= 5"]}, {"level": 1}) is False
        assert evaluate_when({"level": [">= 2", "<= 5"]}, {"level": 6}) is False
        assert evaluate_when({"level": [">= 2", "<= 5"]}, {"level": 2}) is True
        assert evaluate_when({"level": [">= 2", "<= 5"]}, {"level": 5}) is True


# ── ChampionRuleLoader tests ────────────────────────────────────────────────

@pytest.fixture
def rules_dir(tmp_path):
    """Create a temp directory with sample YAML rule files."""
    yasuo_yaml = textwrap.dedent("""\
        champion: Yasuo
        rules:
          - id: yasuo_test_powerspike
            priority: 85
            message: "6级大招就绪"
            tags: [powerspike]
            when:
              level: "== 6"
              hp_pct: ">= 45"
              is_dead: false

          - id: yasuo_test_recall
            priority: 82
            message: "回城买装"
            tags: [economy]
            when:
              gold: ">= 1300"
              is_dead: false
    """)
    (tmp_path / "yasuo.yaml").write_text(yasuo_yaml, encoding="utf-8")

    jinx_yaml = textwrap.dedent("""\
        champion: Jinx
        rules:
          - id: jinx_test_passive
            priority: 88
            message: "被动触发追击"
            tags: [passive]
            when:
              enemy_dead: ">= 1"
              hp_pct: ">= 30"
              is_dead: false
    """)
    (tmp_path / "jinx.yaml").write_text(jinx_yaml, encoding="utf-8")
    return tmp_path


class TestChampionRuleLoader:
    def test_evaluate_matching_champion(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=1500)
        results = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results]
        assert "yasuo_test_powerspike" in ids
        assert "yasuo_test_recall" in ids

    def test_evaluate_no_match_when_conditions_fail(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=3, hp_pct=50, gold=500)
        results = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results]
        assert "yasuo_test_powerspike" not in ids
        assert "yasuo_test_recall" not in ids

    def test_evaluate_unknown_champion_returns_empty(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Garen")
        results = loader.evaluate("Garen", state)
        assert results == []

    def test_evaluate_different_champion(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Jinx", enemy_dead=2, hp_pct=60)
        results = loader.evaluate("Jinx", state)
        ids = [r.rule_id for r in results]
        assert "jinx_test_passive" in ids

    def test_available_champions(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        champs = loader.available_champions()
        assert "yasuo" in champs
        assert "jinx" in champs

    def test_empty_champion_returns_empty(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state()
        assert loader.evaluate("", state) == []

    def test_hot_reload_on_file_change(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=200)
        results = loader.evaluate("Yasuo", state)
        assert any(r.rule_id == "yasuo_test_powerspike" for r in results)

        # Overwrite the file with different rules
        new_yaml = textwrap.dedent("""\
            champion: Yasuo
            rules:
              - id: yasuo_new_rule
                priority: 90
                message: "新规则"
                tags: [test]
                when:
                  level: ">= 1"
                  is_dead: false
        """)
        import time
        time.sleep(0.05)  # Ensure mtime changes
        (rules_dir / "yasuo.yaml").write_text(new_yaml, encoding="utf-8")

        results2 = loader.evaluate("Yasuo", state)
        ids2 = [r.rule_id for r in results2]
        assert "yasuo_new_rule" in ids2
        assert "yasuo_test_powerspike" not in ids2

    def test_rule_result_structure(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=1500)
        results = loader.evaluate("Yasuo", state)
        powerspike = next(r for r in results if r.rule_id == "yasuo_test_powerspike")
        assert isinstance(powerspike, RuleResult)
        assert powerspike.priority == 85
        assert powerspike.message == "6级大招就绪"
        assert powerspike.tags == ("powerspike",)


# ── Integration: loader with real YAML files ─────────────────────────────────

class TestRealYamlFiles:
    """Test against the actual YAML files shipped with the project."""

    def test_yasuo_rules_load(self):
        loader = ChampionRuleLoader()  # uses default _RULES_DIR
        champs = loader.available_champions()
        assert "yasuo" in champs

    def test_yasuo_powerspike_6_fires(self):
        loader = ChampionRuleLoader()
        state = _make_state(champion="Yasuo", level=6, hp_pct=60)
        results = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results]
        assert "yasuo_powerspike_6" in ids

    def test_jinx_passive_fires(self):
        loader = ChampionRuleLoader()
        state = _make_state(champion="Jinx", enemy_dead=2, hp_pct=80)
        results = loader.evaluate("Jinx", state)
        ids = [r.rule_id for r in results]
        assert "jinx_passive_chase" in ids


# ── Cooldown tests ─────────────────────────────────────────────────────────

class TestCooldown:
    def test_rule_suppressed_after_firing(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=1500)
        results1 = loader.evaluate("Yasuo", state)
        assert any(r.rule_id == "yasuo_test_powerspike" for r in results1)

        # Mark the rule as fired
        loader.mark_fired(["yasuo_test_powerspike"])

        # Should be suppressed now (default cooldown = 60s)
        results2 = loader.evaluate("Yasuo", state)
        assert not any(r.rule_id == "yasuo_test_powerspike" for r in results2)

    def test_other_rules_unaffected_by_cooldown(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=1500)
        loader.mark_fired(["yasuo_test_powerspike"])

        results = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results]
        assert "yasuo_test_powerspike" not in ids
        assert "yasuo_test_recall" in ids  # different rule, not on cooldown

    def test_reset_cooldowns_clears_all(self, rules_dir):
        loader = ChampionRuleLoader(rules_dir=rules_dir)
        state = _make_state(champion="Yasuo", level=6, hp_pct=50, gold=1500)
        loader.mark_fired(["yasuo_test_powerspike", "yasuo_test_recall"])

        results_suppressed = loader.evaluate("Yasuo", state)
        assert results_suppressed == []

        loader.reset_cooldowns()
        results_after_reset = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results_after_reset]
        assert "yasuo_test_powerspike" in ids
        assert "yasuo_test_recall" in ids

    def test_custom_cooldown_from_yaml(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            champion: Test
            rules:
              - id: test_short_cd
                priority: 80
                cooldown: 0
                message: "short cooldown"
                tags: [test]
                when:
                  level: ">= 1"
                  is_dead: false
        """)
        (tmp_path / "test.yaml").write_text(yaml_content, encoding="utf-8")
        loader = ChampionRuleLoader(rules_dir=tmp_path)
        state = _make_state(champion="Test", level=6)

        results1 = loader.evaluate("Test", state)
        assert any(r.rule_id == "test_short_cd" for r in results1)

        loader.mark_fired(["test_short_cd"])

        # cooldown=0 means it fires again immediately
        results2 = loader.evaluate("Test", state)
        assert any(r.rule_id == "test_short_cd" for r in results2)


# ── Category selection tests ───────────────────────────────────────────────

class TestCategorySelection:
    def test_select_by_category_picks_best_per_tag(self):
        from src.rule_engine import _select_by_category

        candidates = [
            RuleResult(rule_id="a", priority=80, message="A", tags=("economy",)),
            RuleResult(rule_id="b", priority=90, message="B", tags=("economy",)),
            RuleResult(rule_id="c", priority=85, message="C", tags=("powerspike",)),
        ]
        selected = _select_by_category(candidates)
        ids = [r.rule_id for r in selected]
        # Should pick best from each category: b (economy, 90) and c (powerspike, 85)
        assert "b" in ids
        assert "c" in ids
        assert "a" not in ids  # lower priority in same category
        assert len(selected) == 2

    def test_select_by_category_sorted_by_priority(self):
        from src.rule_engine import _select_by_category

        candidates = [
            RuleResult(rule_id="low", priority=60, message="L", tags=("macro",)),
            RuleResult(rule_id="high", priority=95, message="H", tags=("fight",)),
        ]
        selected = _select_by_category(candidates)
        assert selected[0].rule_id == "high"
        assert selected[1].rule_id == "low"

    def test_select_by_category_single_rule(self):
        from src.rule_engine import _select_by_category

        candidates = [
            RuleResult(rule_id="only", priority=70, message="O", tags=("trade",)),
        ]
        selected = _select_by_category(candidates)
        assert len(selected) == 1
        assert selected[0].rule_id == "only"

    def test_select_by_category_no_tags_uses_default(self):
        from src.rule_engine import _select_by_category

        candidates = [
            RuleResult(rule_id="a", priority=80, message="A", tags=()),
            RuleResult(rule_id="b", priority=90, message="B", tags=()),
        ]
        selected = _select_by_category(candidates)
        # Both have no tags → same _default category → only best kept
        assert len(selected) == 1
        assert selected[0].rule_id == "b"


# ── Contains / not_contains condition tests ────────────────────────────────

class TestContainsCondition:
    def test_contains_match(self):
        assert evaluate_when(
            {"items_lower": "contains kraken"},
            {"items_lower": "kraken slayer|runaan's hurricane"},
        ) is True

    def test_contains_no_match(self):
        assert evaluate_when(
            {"items_lower": "contains infinity"},
            {"items_lower": "kraken slayer|boots"},
        ) is False

    def test_not_contains_match(self):
        assert evaluate_when(
            {"items_lower": "not_contains boots"},
            {"items_lower": "kraken slayer|hurricane"},
        ) is True

    def test_not_contains_no_match(self):
        assert evaluate_when(
            {"items_lower": "not_contains boots"},
            {"items_lower": "kraken slayer|boots of swiftness"},
        ) is False

    def test_contains_case_insensitive(self):
        assert evaluate_when(
            {"items_lower": "contains KRAKEN"},
            {"items_lower": "kraken slayer"},
        ) is True


# ── New metrics in build_context ───────────────────────────────────────────

class TestNewMetrics:
    def test_build_context_normalizes_has_flash(self):
        state = _make_state(has_flash="true", has_tp="false")
        ctx = build_context(state)
        assert ctx["has_flash"] is True
        assert ctx["has_tp"] is False

    def test_build_context_items_lower(self):
        state = _make_state(items="Kraken Slayer|Runaan's Hurricane")
        ctx = build_context(state)
        assert "kraken slayer" in ctx["items_lower"]
        assert "hurricane" in ctx["items_lower"]

    def test_items_rule_fires_on_real_yaml(self):
        loader = ChampionRuleLoader()
        state = _make_state(
            champion="Yasuo",
            items="Infinity Edge|Berserker's Greaves",
            items_lower="infinity edge|berserker's greaves",
            item_count=2,
            hp_pct=60,
            has_flash="true",
        )
        results = loader.evaluate("Yasuo", state)
        ids = [r.rule_id for r in results]
        assert "yasuo_has_ie" in ids

    def test_no_flash_rule_fires(self):
        loader = ChampionRuleLoader()
        state = _make_state(
            champion="Jinx",
            has_flash="false",
            game_time_seconds=600,
            hp_pct=60,
        )
        results = loader.evaluate("Jinx", state)
        ids = [r.rule_id for r in results]
        assert "jinx_no_flash_danger" in ids

    def test_deaths_rule_fires(self):
        loader = ChampionRuleLoader()
        state = _make_state(
            champion="Jinx",
            deaths=5,
            kills=0,
            assists=1,
            game_time_seconds=900,
            hp_pct=60,
        )
        results = loader.evaluate("Jinx", state)
        ids = [r.rule_id for r in results]
        assert "jinx_feeding_safe" in ids
