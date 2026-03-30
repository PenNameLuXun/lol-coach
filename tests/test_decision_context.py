from datetime import datetime, timedelta

from src.decision_context import (
    AnalysisSnapshot,
    ContextWindow,
    build_bridge_prompt,
    build_decision_prompt,
    parse_bridge_output,
)


def test_parse_bridge_output_reads_structured_lines():
    text = "\n".join([
        "scene: river",
        "fight_state: skirmish",
        "player_risk: high",
        "visible_enemies: 2",
        "objective_pressure: dragon",
        "wave_state: neutral",
        "confidence: high",
        "focus: 龙坑拉扯",
        "evidence: 敌方两人已进河道",
    ])
    parsed = parse_bridge_output(text)
    assert parsed["scene"] == "river"
    assert parsed["player_risk"] == "high"
    assert parsed["confidence"] == "high"


def test_context_window_renders_recent_trends():
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
                bridge_facts={"player_risk": "high" if idx >= 1 else "medium", "scene": "river"},
                advice=f"advice {idx}",
            )
        )
    rendered = window.render_for_prompt()
    assert "金币变化 +400" in rendered
    assert "最近风险分布" in rendered
    assert "上一条建议：advice 2" in rendered


def test_prompt_builders_include_safety_context():
    bridge_prompt = build_bridge_prompt("时间12:00，金币1000", {"game_time": "12:00", "gold": 1000, "hp_pct": 75, "level": 8})
    assert "scene:" in bridge_prompt
    decision_prompt = build_decision_prompt(
        system_prompt="你是教练",
        game_summary="时间12:00，金币1000",
        address="Jinx",
        metrics={"game_time": "12:00", "gold": 1000, "hp_pct": 75, "mana_pct": 50, "level": 8, "kda": "1/0/2", "cs": 90},
        bridge_facts={"confidence": "high", "scene": "river", "player_risk": "medium"},
        historical_context="无历史上下文。",
    )
    assert "决策规则" in decision_prompt
    assert "视觉核验置信度：high" in decision_prompt
