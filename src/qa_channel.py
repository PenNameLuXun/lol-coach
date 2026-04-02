from __future__ import annotations

from dataclasses import dataclass

from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.dialogue.source import DialogueSource
from src.rule_engine import ActiveGameContext, RuleAdvice


@dataclass(slots=True)
class QaQuestion:
    speaker: str
    text: str
    source_kind: str
    raw_data: dict


class QaChannel:
    def __init__(self, config_path: str = "config.yaml"):
        self._source = DialogueSource(
            config_path=config_path,
            plugin_id="qa",
            settings_path=("qa",),
        )

    def is_enabled(self, config) -> bool:
        return bool(config.qa_enabled)

    def poll_question(self) -> QaQuestion | None:
        raw_data = self._source.fetch_live_data()
        if not raw_data:
            return None
        payload = raw_data.get("qa", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            return None
        return QaQuestion(
            speaker=str(payload.get("speaker", "玩家")),
            text=text,
            source_kind=str(payload.get("source", "file")),
            raw_data=raw_data,
        )


def build_qa_prompt(
    *,
    question: QaQuestion,
    system_prompt: str,
    active_context: ActiveGameContext | None,
    snapshots: list[AnalysisSnapshot],
    rule_advice: RuleAdvice | None,
    detail: str = "normal",
    address_by: str = "champion",
) -> str:
    if active_context:
        plugin = active_context.plugin
        payload = plugin.build_ai_payload(
            active_context.state,
            detail=detail,
            address_by=address_by,
        )
        game_summary = payload.game_summary or "当前对局上下文为空。"
        game_type = active_context.state.game_type
        rule_hint = rule_advice.hint if rule_advice else "无明确规则提示。"
    else:
        game_summary = "当前没有活跃对局上下文，只能基于通用知识回答。"
        game_type = "none"
        rule_hint = "无规则提示。"

    history_text = _render_qa_history(snapshots)

    return (
        f"{system_prompt}\n\n"
        "当前任务：回答玩家的游戏问题。\n"
        "回答规则：\n"
        "1. 优先结合当前对局上下文回答，如果上下文不足就明确说明你的假设。\n"
        "2. 回答要直接、可执行，优先给 2 到 4 个关键建议。\n"
        "3. 适合 TTS 播报，尽量控制在 120 字以内。\n"
        "4. 不要输出分点编号，不要复述系统设定。\n\n"
        f"提问者：{question.speaker}\n"
        f"问题来源：{question.source_kind}\n"
        f"当前问题：{question.text}\n"
        f"当前游戏类型：{game_type}\n"
        f"当前对局摘要：{game_summary}\n"
        f"当前规则提示：{rule_hint}\n"
        f"最近建议历史：\n{history_text}"
    )


def _render_qa_history(snapshots: list[AnalysisSnapshot]) -> str:
    if not snapshots:
        return "无历史建议。"
    lines = []
    for snap in snapshots[-4:]:
        lines.append(f"{snap.timestamp.strftime('%H:%M:%S')} {snap.advice}")
    return "\n".join(lines)
