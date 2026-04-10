from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.dialogue.source import DialogueSource
from src.qa_web_search import (
    SearchDocument,
    SearchSite,
    format_search_documents,
    search_web_for_qa,
    should_web_search_question,
)
from src.rule_engine import ActiveGameContext, RuleAdvice


@dataclass(slots=True)
class QaQuestion:
    speaker: str
    text: str
    source_kind: str
    raw_data: dict
    wakeword_triggered: bool = False
    wakeword_only: bool = False


class QaChannel:
    def __init__(self, config_path: str = "config.yaml"):
        self._source = DialogueSource(
            config_path=config_path,
            plugin_id="qa",
            settings_path=("qa",),
        )
        self._input_line_index_by_path: dict[str, int] = {}
        self._input_initialized_paths: set[str] = set()
        self._last_question_key = ""
        self._last_question_at = 0.0
        self._duplicate_cooldown_seconds = 20.0
        self._wakeword_listen_until = 0.0
        self._wakeword_followup_window_seconds = 8.0
        self._last_partial_text = ""

    def is_enabled(self, config) -> bool:
        return bool(config.qa_enabled)

    def pause_microphone(self) -> None:
        self._source.pause_microphone()

    def resume_microphone(self) -> bool:
        return self._source.resume_microphone()

    def stop(self) -> None:
        self._source.stop()

    def flush_transcript(self) -> None:
        """Advance the line index to current end-of-file, discarding lines written during TTS playback."""
        cfg = self._source._source_config()
        transcript_path = (
            self._source._config_path.parent
            / str(cfg.get("transcript_file", "game_qa_mic.txt"))
        )
        if not transcript_path.exists():
            return
        try:
            lines = [
                line.strip()
                for line in transcript_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception:
            return
        resolved = os.fspath(transcript_path.resolve())
        old_index = self._source._line_index_by_path.get(resolved, len(lines))
        skipped = max(0, len(lines) - old_index)
        if skipped:
            print(f"[QA flush] discarded {skipped} echo line(s) written during TTS")
        self._source._line_index_by_path[resolved] = len(lines)
        self._source._append_initialized_paths.add(resolved)

    def poll_partial_question_text(self) -> str | None:
        cfg = self._source._source_config()
        if str(cfg.get("source", "file")) != "microphone":
            return None
        transcript_path = (
            self._source._config_path.parent
            / str(cfg.get("transcript_file", "game_qa_mic.txt"))
        )
        partial_path = transcript_path.with_suffix(transcript_path.suffix + ".partial")
        text = ""
        try:
            if partial_path.exists():
                text = partial_path.read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        if not text:
            self._last_partial_text = ""
            return None
        partial_text = self._preview_partial_text(text, cfg)
        if not partial_text:
            return None
        if partial_text == self._last_partial_text:
            return None
        self._last_partial_text = partial_text
        return partial_text

    def poll_question(self) -> QaQuestion | None:
        cfg = self._source._source_config()
        source_kind = str(cfg.get("source", "file"))
        if source_kind == "file":
            transcript_path = self._source._config_path.parent / str(cfg.get("transcript_file", "game_qa_mic.txt"))
            self._source._prepare_append_only_path(transcript_path)
            self._ingest_file_questions(cfg, transcript_path)
            raw_data = self._source._read_append_only_payload(
                path=transcript_path,
                speaker=str(cfg.get("speaker", "玩家")),
                source_kind="file",
            )
        else:
            raw_data = self._source.fetch_live_data()
        if not raw_data:
            return None
        payload = raw_data.get("qa", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            return None
        text, wakeword_triggered, wakeword_only = self._apply_wakeword_gate(text, cfg)
        if not text and not wakeword_only:
            return None
        question_key = _normalize_question_text(text)
        now = time.perf_counter()
        if (
            not wakeword_only
            and question_key
            and question_key == self._last_question_key
            and now - self._last_question_at < self._duplicate_cooldown_seconds
        ):
            print(f"[QA] suppressed duplicate question within {self._duplicate_cooldown_seconds:.0f}s: {text}")
            return None
        if not wakeword_only:
            self._last_question_key = question_key
            self._last_question_at = now
            self._last_partial_text = ""
        return QaQuestion(
            speaker=str(payload.get("speaker", "玩家")),
            text=text,
            source_kind=str(payload.get("source", "file")),
            raw_data=raw_data,
            wakeword_triggered=wakeword_triggered,
            wakeword_only=wakeword_only,
        )

    def _ingest_file_questions(self, cfg: dict, transcript_path) -> None:
        input_path = self._source._config_path.parent / str(cfg.get("text_file", "game_qa_input.txt"))
        if not input_path.exists():
            return
        try:
            lines = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return
        if not lines:
            return

        resolved = str(input_path.resolve())
        if resolved not in self._input_initialized_paths:
            self._input_line_index_by_path[resolved] = len(lines)
            self._input_initialized_paths.add(resolved)
            return

        index = self._input_line_index_by_path.get(resolved, 0)
        if index > len(lines):
            index = 0
        new_lines = lines[index:]
        if not new_lines:
            return

        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        if not transcript_path.exists():
            transcript_path.write_text("", encoding="utf-8")
        self._source._prepare_append_only_path(transcript_path)
        with transcript_path.open("a", encoding="utf-8") as handle:
            for line in new_lines:
                handle.write(line + "\n")
        self._input_line_index_by_path[resolved] = len(lines)

    def _apply_wakeword_gate(self, text: str, cfg: dict) -> tuple[str, bool, bool]:
        if not bool(cfg.get("wakeword_enabled", False)):
            return text, False, False
        raw_keywords = str(cfg.get("wakeword_keywords_text", "")).strip()
        keywords = [line.strip() for line in raw_keywords.splitlines() if line.strip()]
        if not keywords:
            return text, False, False
        stripped = text.strip()
        normalized = _normalize_question_text(stripped)
        now = time.perf_counter()
        for keyword in keywords:
            keyword_norm = _normalize_question_text(keyword)
            if not keyword_norm:
                continue
            if normalized.startswith(keyword_norm):
                remainder = stripped[len(keyword):].lstrip(" ,，。.:：!?！？-")
                remainder = remainder.strip()
                self._wakeword_listen_until = now + self._wakeword_followup_window_seconds
                if remainder:
                    return remainder, True, False
                return "", True, True
        if now < self._wakeword_listen_until:
            return stripped, False, False
        return "", False, False

    def _preview_partial_text(self, text: str, cfg: dict) -> str:
        stripped = str(text or "").strip()
        if not stripped:
            return ""
        if not bool(cfg.get("wakeword_enabled", False)):
            return stripped
        raw_keywords = str(cfg.get("wakeword_keywords_text", "")).strip()
        keywords = [line.strip() for line in raw_keywords.splitlines() if line.strip()]
        if not keywords:
            return stripped
        normalized = _normalize_question_text(stripped)
        for keyword in keywords:
            keyword_norm = _normalize_question_text(keyword)
            if keyword_norm and normalized.startswith(keyword_norm):
                remainder = stripped[len(keyword):].lstrip(" ,，。.:：!?！？-").strip()
                return remainder or keyword
        if time.perf_counter() < self._wakeword_listen_until:
            return stripped
        return ""


def build_qa_prompt(
    *,
    question: QaQuestion,
    system_prompt: str,
    active_context: ActiveGameContext | None,
    snapshots: list[AnalysisSnapshot],
    rule_advice: RuleAdvice | None,
    web_search_docs: list[SearchDocument] | None = None,
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
    web_search_text = format_search_documents(web_search_docs or [])

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
        f"最近建议历史：\n{history_text}\n\n"
        f"联网搜索资料：\n{web_search_text}"
    )


def build_qa_followup_prompt(
    *,
    question: QaQuestion,
    initial_answer: str,
    system_prompt: str,
    active_context: ActiveGameContext | None,
    snapshots: list[AnalysisSnapshot],
    rule_advice: RuleAdvice | None,
    web_search_docs: list[SearchDocument],
    detail: str = "normal",
    address_by: str = "champion",
) -> str:
    base_prompt = build_qa_prompt(
        question=question,
        system_prompt=system_prompt,
        active_context=active_context,
        snapshots=snapshots,
        rule_advice=rule_advice,
        web_search_docs=web_search_docs,
        detail=detail,
        address_by=address_by,
    )
    return (
        f"{base_prompt}\n\n"
        "你已经先给出过一版首答。\n"
        "首答内容：\n"
        f"{initial_answer}\n\n"
        "现在请基于联网搜索资料，只在以下情况下输出“补充说明”：\n"
        "1. 搜索结果提供了更具体的版本/出装/玩法信息；\n"
        "2. 首答里有需要修正或补充的地方；\n"
        "3. 能给出更准确的 1 到 2 句可执行建议。\n"
        "如果搜索资料没有带来明显增量，请只输出：无补充。\n"
        "如果需要补充，请直接输出短的补充内容，不要重复整段首答，不要编号。"
    )


def run_qa_web_search(
    *,
    question: QaQuestion,
    config,
    active_context: ActiveGameContext | None,
) -> list[SearchDocument]:
    if not config.qa_web_search_enabled or config.qa_web_search_mode == "off":
        return []
    if config.qa_web_search_mode == "auto" and not should_web_search_question(question.text):
        return []
    plugin_id = active_context.plugin.id if active_context else None
    sites = config.qa_web_search_sites(plugin_id)
    if not sites:
        return []
    try:
        return search_web_for_qa(
            question=question.text,
            engine=config.qa_web_search_engine,
            sites=[SearchSite(domain=str(site["domain"]), priority=int(site["priority"])) for site in sites],
            timeout_seconds=config.qa_web_search_timeout_seconds,
            max_results_per_site=config.qa_web_search_max_results_per_site,
            max_pages=config.qa_web_search_max_pages,
            accept_language=config.qa_web_search_accept_language,
        )
    except Exception as exc:
        print(f"[QA search error] {exc}")
        return []


def _render_qa_history(snapshots: list[AnalysisSnapshot]) -> str:
    if not snapshots:
        return "无历史建议。"
    lines = []
    for snap in snapshots[-4:]:
        lines.append(f"{snap.timestamp.strftime('%H:%M:%S')} {snap.advice}")
    return "\n".join(lines)


def _normalize_question_text(text: str) -> str:
    normalized = re.sub(r"\s+", "", str(text or "")).strip().lower()
    return normalized
