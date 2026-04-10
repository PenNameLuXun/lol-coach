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
from src.qa_channel import QaChannel, build_qa_prompt, run_qa_web_search
from src.workers.shared import SignalBridge, QaRuntimeContext, log_with_timestamp

logger = logging.getLogger("lol_coach.qa_worker")
_SENTENCE_SPLIT_RE = re.compile(r"(.+?[。！？!?；;](?:\s|$))")


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


def _wait_until_tts_slot_available(stop_event: threading.Event, tts_busy_event: threading.Event, timeout_seconds: float = 8.0):
    deadline = time.perf_counter() + timeout_seconds
    while tts_busy_event.is_set() and not stop_event.is_set():
        if time.perf_counter() >= deadline:
            break
        stop_event.wait(timeout=0.05)


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
    poll_interval_seconds = 0.2
    provider_cache = _ProviderCache()

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
        if tts_busy_now and not config.qa_wakeword_enabled:
            if not mic_paused_for_tts:
                qa_channel.pause_microphone()
                mic_paused_for_tts = True
            qa_channel.flush_transcript()
            continue

        if not _qa_hotkey_gate_open(config):
            if mic_paused_for_tts:
                qa_channel.resume_microphone()
                mic_paused_for_tts = False
            qa_channel.flush_transcript()
            continue

        if mic_paused_for_tts:
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

            prompt = build_qa_prompt(
                question=question,
                system_prompt=config.qa_system_prompt,
                active_context=active_context,
                snapshots=snapshots,
                rule_advice=rule_advice,
                web_search_docs=web_search_docs,
                detail=config.plugin_detail(active_plugin_id),
                address_by=config.plugin_address_by(active_plugin_id),
            )
            provider_started_at = time.perf_counter()
            message_id = f"qa-{time.time_ns()}"
            text_chunks: list[str] = []
            sentence_queue: deque[str] = deque()
            sentence_buffer = ""
            bridge.overlay_event.emit(
                {
                    "kind": "qa_output",
                    "text": "思考中…",
                    "message_id": message_id,
                    "replace": True,
                    "final": False,
                }
            )
            for chunk in provider.analyze_stream(None, prompt):
                if not chunk:
                    continue
                text_chunks.append(chunk)
                sentence_buffer += chunk
                sentence_buffer = _stream_sentences(sentence_buffer, sentence_queue)
                current_text = "".join(text_chunks).strip()
                if current_text:
                    bridge.overlay_event.emit(
                        {
                            "kind": "qa_output",
                            "text": current_text,
                            "message_id": message_id,
                            "replace": True,
                            "final": False,
                        }
                    )
                while sentence_queue:
                    sentence = sentence_queue.popleft()
                    _wait_until_tts_slot_available(stop_event, tts_busy_event)
                    if stop_event.is_set():
                        break
                    bus.put_advice(
                        sentence,
                        source="qa",
                        expires_after_seconds=20.0,
                        interruptible=False,
                    )
            text = "".join(text_chunks).strip()
            if sentence_buffer.strip():
                sentence_queue.append(sentence_buffer.strip())
            while sentence_queue and not stop_event.is_set():
                sentence = sentence_queue.popleft()
                _wait_until_tts_slot_available(stop_event, tts_busy_event)
                if stop_event.is_set():
                    break
                bus.put_advice(
                    sentence,
                    source="qa",
                    expires_after_seconds=20.0,
                    interruptible=False,
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
                    "[timing] reason=qa bridge_ms=0 provider_ms=%.0f total_ms=%.0f",
                    provider_elapsed_ms, total_elapsed_ms,
                )
            bridge.overlay_event.emit(
                {
                    "kind": "qa_output",
                    "text": text or "未生成有效回答。",
                    "message_id": message_id,
                    "replace": True,
                    "final": True,
                }
            )
            if text:
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
        except Exception as exc:
            logger.error("[QA worker error] %s", exc)
