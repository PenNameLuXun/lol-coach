"""TTS playback worker thread — consumes advice events, speaks via TTS engine."""

import logging
import queue
import threading
import time

from src.config import Config
from src.event_bus import EventBus, AdviceEvent
from src.tts_engine import get_tts_engine
from src.workers.shared import log_with_timestamp

logger = logging.getLogger("lol_coach.tts_worker")


def _resolve_tts_rate_override(config: Config, backend: str, engine, text: str) -> int | None:
    mode = config.tts_playback_mode
    if mode not in {"fit_wait", "fit_continue"}:
        return None
    if backend != "windows" or not engine.supports_dynamic_rate():
        return None
    target_seconds = max(1.0, config.scheduler_interval * 0.9)
    base_rate = int(config.tts_config("windows").get("rate", 0))
    text_len = max(1, len(text.strip()))
    estimated_chars_per_sec = max(1.6, 3.0 + base_rate * 0.18)
    desired_chars_per_sec = text_len / max(0.6, target_seconds - 0.4)
    desired_rate = round((desired_chars_per_sec - 3.0) / 0.18)
    return max(-10, min(10, max(base_rate, desired_rate)))


def _should_interrupt_current(
    current_event: AdviceEvent | None,
    incoming_event: AdviceEvent | None,
    playback_mode: str,
    supports_interrupt: bool,
) -> bool:
    if not supports_interrupt or current_event is None or incoming_event is None:
        return False
    if getattr(incoming_event, "source", "") == "qa" and getattr(current_event, "source", "") != "qa":
        return True
    if not bool(getattr(current_event, "interruptible", True)):
        return False
    return playback_mode == "interrupt" and bool(getattr(incoming_event, "interruptible", True))


def tts_worker(
    bus: EventBus,
    config: Config,
    stop_event: threading.Event,
    busy_event: threading.Event,
    interrupt_event: threading.Event,
):
    current_engine = None
    current_backend = None
    current_cfg = None

    def get_engine():
        nonlocal current_engine, current_backend, current_cfg
        backend = config.tts_backend
        cfg = dict(config.tts_config(backend))
        if current_engine is None or backend != current_backend or cfg != current_cfg:
            current_engine = get_tts_engine(backend, cfg)
            current_backend = backend
            current_cfg = cfg
        return current_engine

    active_event = None
    active_started_at = 0.0

    while not stop_event.is_set():
        try:
            engine = get_engine()
            playback_mode = config.tts_playback_mode
            supports_interrupt = engine.supports_interrupt()
            if supports_interrupt:
                if active_event is not None:
                    if engine.is_busy():
                        busy_event.set()
                        if interrupt_event.is_set():
                            log_with_timestamp("TTS", "interrupt requested by wakeword")
                            interrupt_event.clear()
                            engine.interrupt()
                            while engine.is_busy() and not stop_event.wait(timeout=0.02):
                                pass
                            elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                            log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f} interrupted=true")
                            active_event = None
                            busy_event.clear()
                            continue
                        try:
                            next_event = bus.get_latest_advice_event(timeout=0.1)
                        except queue.Empty:
                            continue
                        if not _should_interrupt_current(active_event, next_event, playback_mode, supports_interrupt):
                            bus.put_advice(
                                next_event.text,
                                source=next_event.source,
                                priority=next_event.priority,
                                expires_after_seconds=next_event.expires_after_seconds,
                                dedupe_key=next_event.dedupe_key,
                                interruptible=next_event.interruptible,
                            )
                            continue
                        log_with_timestamp("TTS", f"interrupt len={len(next_event.text)} text={next_event.text[:60]}")
                        engine.interrupt()
                        while engine.is_busy() and not stop_event.wait(timeout=0.02):
                            pass
                        elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                        log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f} interrupted=true")
                        active_event = next_event
                        active_started_at = time.perf_counter()
                        log_with_timestamp("TTS", f"start len={len(active_event.text)} text={active_event.text[:60]}")
                        busy_event.set()
                        engine.start(
                            active_event.text,
                            rate_override=_resolve_tts_rate_override(config, current_backend, engine, active_event.text),
                        )
                        continue
                    elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                    log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
                    active_event = None
                    busy_event.clear()
                    continue

                try:
                    active_event = bus.get_latest_advice_event(timeout=1.0)
                except queue.Empty:
                    continue
                active_started_at = time.perf_counter()
                log_with_timestamp("TTS", f"start len={len(active_event.text)} text={active_event.text[:60]}")
                busy_event.set()
                engine.start(
                    active_event.text,
                    rate_override=_resolve_tts_rate_override(config, current_backend, engine, active_event.text),
                )
                continue

            try:
                text = bus.get_latest_advice(timeout=1.0)
            except queue.Empty:
                continue
            started_at = time.perf_counter()
            log_with_timestamp("TTS", f"start len={len(text)} text={text[:60]}")
            busy_event.set()
            engine.speak(text, rate_override=_resolve_tts_rate_override(config, current_backend, engine, text))
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
        except Exception as e:
            logger.error("[TTS worker error] %s", e)
            busy_event.clear()
            active_event = None
        finally:
            if active_event is None and not stop_event.is_set():
                busy_event.clear()
