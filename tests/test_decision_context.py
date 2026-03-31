from datetime import datetime, timedelta

from src.analysis_flow import (
    AnalysisSnapshot,
    ContextWindow,
    choose_analysis_plan,
    parse_bridge_output,
)


def test_parse_bridge_output_reads_structured_lines():
    text = "\n".join([
        "scene: river",
        "fight_state: skirmish",
        "player_risk: high",
        "threat_level: critical",
        "ally_support: outnumbered",
        "visible_enemies: 2",
        "objective_pressure: dragon",
        "resource_window: contest_objective",
        "map_control: contested",
        "engage_window: bad",
        "wave_state: neutral",
        "confidence: high",
        "focus: 龙坑拉扯",
        "evidence: 敌方两人已进河道",
    ])
    parsed = parse_bridge_output(text)
    assert parsed["scene"] == "river"
    assert parsed["player_risk"] == "high"
    assert parsed["threat_level"] == "critical"
    assert parsed["confidence"] == "high"


def test_context_window_keeps_recent_snapshots():
    window = ContextWindow(limit=5)
    base = datetime(2026, 1, 1, 12, 0, 0)
    for idx in range(3):
        window.add(
            AnalysisSnapshot(
                timestamp=base + timedelta(seconds=idx * 30),
                game_summary=f"summary {idx}",
                address="Jinx",
                metrics={
                    "game_time": f"12:{idx:02d}",
                    "gold": 1000 + idx * 200,
                    "level": 8 + idx,
                    "cs": 90 + idx * 10,
                    "hp_pct": 80 - idx * 20,
                },
                bridge_facts={
                    "player_risk": "high" if idx >= 1 else "medium",
                    "threat_level": "critical" if idx >= 1 else "pressured",
                    "resource_window": "contest_objective",
                    "scene": "river",
                },
                advice=f"advice {idx}",
            )
        )
    assert window.latest() is not None
    assert window.latest().advice == "advice 2"
    assert len(window.items()) == 3


def test_choose_analysis_plan_skips_stable_cycles():
    previous = AnalysisSnapshot(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        game_summary="summary",
        address="Jinx",
        metrics={"game_time": "12:00", "gold": 1000, "level": 8, "cs": 90, "hp_pct": 70, "event_signature": "none"},
        bridge_facts={"threat_level": "stable", "resource_window": "farm"},
        advice="补刀",
    )
    plan = choose_analysis_plan(
        current_metrics={"game_time": "12:05", "gold": 1050, "level": 8, "cs": 92, "hp_pct": 68, "event_signature": "none"},
        previous_snapshot=previous,
        has_image=True,
        now=datetime(2026, 1, 1, 12, 0, 15),
        trigger_cfg={"force_after_seconds": 45, "hp_drop_pct": 20, "gold_delta": 350, "cs_delta": 8, "skip_stable_cycles": True},
    )
    assert plan.should_analyze is False
    assert plan.reason == "stable_skip"


def test_choose_analysis_plan_runs_bridge_on_event_change():
    previous = AnalysisSnapshot(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        game_summary="summary",
        address="Jinx",
        metrics={"game_time": "12:00", "gold": 1000, "level": 8, "cs": 90, "hp_pct": 70, "event_signature": "none"},
        bridge_facts={"threat_level": "stable", "resource_window": "farm"},
        advice="补刀",
    )
    plan = choose_analysis_plan(
        current_metrics={"game_time": "12:05", "gold": 1050, "level": 8, "cs": 92, "hp_pct": 68, "event_signature": "DragonKill"},
        previous_snapshot=previous,
        has_image=True,
        now=datetime(2026, 1, 1, 12, 0, 15),
        trigger_cfg={"force_after_seconds": 45, "hp_drop_pct": 20, "gold_delta": 350, "cs_delta": 8, "skip_stable_cycles": True},
    )
    assert plan.should_analyze is True
    assert plan.run_bridge is True
    assert plan.reason == "event_change"
