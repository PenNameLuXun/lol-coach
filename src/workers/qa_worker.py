"""QA (question-answering) worker thread — polls for user questions, queries AI."""

import logging
import random
import re
import threading
import time
from collections import deque

from src.ai_provider import get_provider, BaseProvider
from src.config import Config
from src.event_bus import EventBus
from src.qa_channel import QaChannel, build_qa_followup_prompt, build_qa_prompt, run_qa_web_search
from src.workers.shared import SignalBridge, QaRuntimeContext, log_with_timestamp

logger = logging.getLogger("lol_coach.qa_worker")
_SENTENCE_SPLIT_RE = re.compile(r"(.+?(?:[。！？!?；;](?:\s|$)|\n))")


def _qa_hotkey_gate_open(config: Config) -> bool:
    if config.qa_settings.get("source", "file") != "microphone":
        return True
    if config.qa_microphone_trigger_mode != "hold":
        return True
    hotkey = config.qa_microphone_hotkey
    if not hotkey:
        return False
    try:
        import keyboard
        return bool(keyboard.is_pressed(hotkey))
    except Exception:
        return False


class _ProviderCache:
    """Caches the AI provider instance, only re-creating when config changes."""

    def __init__(self):
        self._provider: BaseProvider | None = None
        self._provider_name: str | None = None
        self._provider_cfg: dict | None = None

    def get(self, config: Config) -> BaseProvider:
        name = config.ai_provider
        cfg = dict(config.ai_config(name))
        if self._provider is None or name != self._provider_name or cfg != self._provider_cfg:
            self._provider = get_provider(name, cfg)
            self._provider_name = name
            self._provider_cfg = cfg
        return self._provider


def _stream_sentences(buffer: str, pending: deque[str]) -> str:
    while True:
        match = _SENTENCE_SPLIT_RE.match(buffer)
        if not match:
            break
        sentence = match.group(1).strip()
        if sentence:
            pending.append(sentence)
        buffer = buffer[match.end():]
    return buffer


def _wait_until_tts_slot_available(
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    timeout_seconds: float = 8.0,
    interrupt_event: threading.Event | None = None,
):
    deadline = time.perf_counter() + timeout_seconds
    while tts_busy_event.is_set() and not stop_event.is_set():
        if interrupt_event is not None and interrupt_event.is_set():
            break
        if time.perf_counter() >= deadline:
            break
        stop_event.wait(timeout=0.05)


def _stream_answer_to_overlay_and_tts(
    *,
    provider: BaseProvider,
    prompt: str,
    bridge: SignalBridge,
    bus: EventBus,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tts_interrupt_event: threading.Event,
    message_id: str,
    overlay_kind: str,
    placeholder: str,
    tts_source: str,
    final_fallback: str,
) -> str:
    def _should_abort() -> bool:
        return stop_event.is_set() or tts_interrupt_event.is_set()

    text_chunks: list[str] = []
    sentence_queue: deque[str] = deque()
    sentence_buffer = ""
    bridge.overlay_event.emit(
        {
            "kind": overlay_kind,
            "text": placeholder,
            "message_id": message_id,
            "replace": True,
            "final": False,
        }
    )
    for chunk in provider.analyze_stream(None, prompt):
        if _should_abort():
            break
        if not chunk:
            continue
        text_chunks.append(chunk)
        sentence_buffer += chunk
        sentence_buffer = _stream_sentences(sentence_buffer, sentence_queue)
        current_text = "".join(text_chunks).strip()
        if current_text:
            bridge.overlay_event.emit(
                {
                    "kind": overlay_kind,
                    "text": current_text,
                    "message_id": message_id,
                    "replace": True,
                    "final": False,
                }
            )
        while sentence_queue:
            sentence = sentence_queue.popleft()
            _wait_until_tts_slot_available(stop_event, tts_busy_event, interrupt_event=tts_interrupt_event)
            if _should_abort():
                break
            bus.put_advice(
                sentence,
                source=tts_source,
                expires_after_seconds=20.0,
                interruptible=False,
            )
        if _should_abort():
            break
    text = "".join(text_chunks).strip()
    if not _should_abort() and sentence_buffer.strip():
        sentence_queue.append(sentence_buffer.strip())
    while sentence_queue and not _should_abort():
        sentence = sentence_queue.popleft()
        _wait_until_tts_slot_available(stop_event, tts_busy_event, interrupt_event=tts_interrupt_event)
        if _should_abort():
            break
        bus.put_advice(
            sentence,
            source=tts_source,
            expires_after_seconds=20.0,
            interruptible=False,
        )
    bridge.overlay_event.emit(
        {
            "kind": overlay_kind,
            "text": text or final_fallback,
            "message_id": message_id,
            "replace": True,
            "final": True,
        }
    )
    return text


def qa_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tts_interrupt_event: threading.Event,
    qa_channel: QaChannel,
    qa_runtime: QaRuntimeContext,
    debug_timing: bool = False,
):
    mic_paused_for_tts = False
    tts_was_busy = False
    tts_suppress_until = 0.0
    poll_interval_seconds = 0.2
    provider_cache = _ProviderCache()
    chat_history: deque[tuple[str, str]] = deque(maxlen=6)  # 最近 6 轮问答对

    while not stop_event.is_set():
        stop_event.wait(timeout=poll_interval_seconds)
        if stop_event.is_set():
            break
        if not qa_channel.is_enabled(config):
            continue

        partial_text = qa_channel.poll_partial_question_text()
        if partial_text:
            bridge.overlay_event.emit(
                {
                    "kind": "qa_input",
                    "text": partial_text,
                    "message_id": "qa-live-input",
                    "replace": True,
                    "final": False,
                }
            )

        tts_busy_now = tts_busy_event.is_set()
        now_mono = time.perf_counter()

        # TTS 刚结束：flush 掉 Whisper 缓冲区里尚未写完的回声行，再等一小段冷却期
        if tts_was_busy and not tts_busy_now:
            qa_channel.flush_transcript()
            suppress_secs = float(config.qa_settings.get("post_tts_suppress_seconds", 1.5))
            tts_suppress_until = now_mono + suppress_secs
        tts_was_busy = tts_busy_now

        wakeword_mode = config.qa_wakeword_enabled

        if tts_busy_now and not wakeword_mode:
            # TTS 播放中（非唤醒词模式）：暂停麦克风并持续 flush
            if not mic_paused_for_tts:
                qa_channel.pause_microphone()
                mic_paused_for_tts = True
            qa_channel.flush_transcript()
            continue

        if not wakeword_mode and now_mono < tts_suppress_until:
            # TTS 结束后冷却期：Whisper 可能还在处理缓冲音频，继续 flush 不处理问题
            qa_channel.flush_transcript()
            continue

        if not _qa_hotkey_gate_open(config):
            if mic_paused_for_tts:
                qa_channel.flush_transcript()
                qa_channel.resume_microphone()
                mic_paused_for_tts = False
            qa_channel.flush_transcript()
            continue

        if mic_paused_for_tts:
            # 恢复麦克风前先 flush，丢弃 Whisper 对已暂停前缓冲音频的滞后转写结果
            qa_channel.flush_transcript()
            qa_channel.resume_microphone()
            mic_paused_for_tts = False

        question = qa_channel.poll_question()
        if question is None:
            continue

        bridge.overlay_event.emit({"kind": "qa_input", "text": question.text})
        bridge.overlay_event.emit(
            {
                "kind": "qa_input",
                "text": question.text,
                "message_id": "qa-live-input",
                "replace": True,
                "final": True,
            }
        )

        if question.wakeword_triggered and config.qa_wakeword_enabled:
            log_with_timestamp("QA", "wakeword matched, requesting interrupt")
            tts_interrupt_event.set()
            ack_text = random.choice(config.qa_wakeword_ack_texts)
            bus.put_advice(
                ack_text,
                source="qa_ack",
                expires_after_seconds=3.0,
                interruptible=False,
            )
            bus.emit_advice(ack_text)
            bridge.advice_ready.emit(ack_text)
            bridge.overlay_event.emit({"kind": "qa_ack", "text": ack_text})
            if question.wakeword_only:
                continue

        active_context, rule_advice, snapshots = qa_runtime.snapshot()
        active_plugin_id = active_context.plugin.id if active_context else None
        cycle_started_at = time.perf_counter()
        log_with_timestamp("QA", f"question={question.text!r} source={question.source_kind}")

        try:
            provider = provider_cache.get(config)
            prompt = build_qa_prompt(
                question=question,
                system_prompt=config.qa_system_prompt,
                active_context=active_context,
                snapshots=snapshots,
                rule_advice=rule_advice,
                web_search_docs=[],
                detail=config.plugin_detail(active_plugin_id),
                address_by=config.plugin_address_by(active_plugin_id),
                topic=config.qa_topic,
                chat_history=list(chat_history),
            )
            provider_started_at = time.perf_counter()
            message_id = f"qa-{time.time_ns()}"
            text = _stream_answer_to_overlay_and_tts(
                provider=provider,
                prompt=prompt,
                bridge=bridge,
                bus=bus,
                stop_event=stop_event,
                tts_busy_event=tts_busy_event,
                tts_interrupt_event=tts_interrupt_event,
                message_id=message_id,
                overlay_kind="qa_output",
                placeholder="思考中…",
                tts_source="qa",
                final_fallback="未生成有效回答。",
            )
            provider_elapsed_ms = (time.perf_counter() - provider_started_at) * 1000
            total_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
            log_with_timestamp(
                "QA timing",
                f"provider={config.ai_provider} "
                f"provider_ms={provider_elapsed_ms:.0f} "
                f"total_ms={total_elapsed_ms:.0f}",
            )
            if debug_timing:
                logger.info(
                    "[timing] reason=qa:first bridge_ms=0 provider_ms=%.0f total_ms=%.0f",
                    provider_elapsed_ms, total_elapsed_ms,
                )
            if text:
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                if config.qa_topic == "chat":
                    chat_history.append((question.text, text))

            search_started_at = time.perf_counter()
            web_search_docs = run_qa_web_search(
                question=question,
                config=config,
                active_context=active_context,
            )
            search_elapsed_ms = (time.perf_counter() - search_started_at) * 1000
            log_with_timestamp(
                "QA search",
                f"enabled={config.qa_web_search_enabled} "
                f"mode={config.qa_web_search_mode} "
                f"engine={config.qa_web_search_engine} "
                f"docs={len(web_search_docs)} "
                f"elapsed_ms={search_elapsed_ms:.0f}",
            )
            for i, doc in enumerate(web_search_docs, 1):
                log_with_timestamp(
                    "QA search result",
                    f"[{i}] site={doc.domain} title={doc.title!r} url={doc.url}",
                )
            if not web_search_docs:
                continue

            followup_prompt = build_qa_followup_prompt(
                question=question,
                initial_answer=text,
                system_prompt=config.qa_system_prompt,
                active_context=active_context,
                snapshots=snapshots,
                rule_advice=rule_advice,
                web_search_docs=web_search_docs,
                detail=config.plugin_detail(active_plugin_id),
                address_by=config.plugin_address_by(active_plugin_id),
                topic=config.qa_topic,
                chat_history=list(chat_history),
            )
            followup_started_at = time.perf_counter()
            followup_id = f"{message_id}-followup"
            followup_text = _stream_answer_to_overlay_and_tts(
                provider=provider,
                prompt=followup_prompt,
                bridge=bridge,
                bus=bus,
                stop_event=stop_event,
                tts_busy_event=tts_busy_event,
                tts_interrupt_event=tts_interrupt_event,
                message_id=followup_id,
                overlay_kind="qa_output",
                placeholder="检索补充中…",
                tts_source="qa",
                final_fallback="无补充。",
            ).strip()
            followup_elapsed_ms = (time.perf_counter() - followup_started_at) * 1000
            if followup_text in {"", "无补充。", "无补充"}:
                bridge.overlay_event.emit(
                    {
                        "kind": "qa_output",
                        "text": "无补充。",
                        "message_id": followup_id,
                        "replace": True,
                        "final": True,
                    }
                )
                continue
            total_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
            log_with_timestamp(
                "QA followup",
                f"provider={config.ai_provider} followup_ms={followup_elapsed_ms:.0f} total_ms={total_elapsed_ms:.0f}",
            )
            if debug_timing:
                logger.info(
                    "[timing] reason=qa:followup bridge_ms=0 provider_ms=%.0f total_ms=%.0f",
                    followup_elapsed_ms, total_elapsed_ms,
                )
            bus.emit_advice(followup_text)
            bridge.advice_ready.emit(followup_text)
        except Exception as exc:
            logger.error("[QA worker error] %s", exc)
