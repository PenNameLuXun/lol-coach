"""LOL Coach — entry point.

Wires all components together:
- Config → loaded from config.yaml (copied from config.example.yaml on first run)
- EventBus → shared queues between threads
- Capturer → screenshot daemon thread
- AI worker thread → consumes capture_queue, produces advice
- TTS worker thread → consumes advice_queue
- History → SQLite, accessed from main thread via signals
- UI → MainWindow (hidden), TrayIcon, OverlayWindow
"""

import argparse
import datetime
import queue
import shutil
import signal
import sys
import threading
import os
import subprocess
import time

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from src.analysis_flow import (
    AnalysisSnapshot,
    AnalysisPlan,
    ContextWindow,
    choose_analysis_plan,
    parse_bridge_output,
)
from src.config import Config
from src.event_bus import EventBus
from src.history import History
from src.capturer import Capturer
from src.ai_provider import get_provider
from src.tts_engine import get_tts_engine
from src.game_plugins.base import AiPayload
from src.rule_engine import RuleEngine
from src.qa_channel import QaChannel, build_qa_prompt, run_qa_web_search
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow


# ── Qt Signal bridge from worker threads to UI ────────────────────────────────

class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)


def _log_with_timestamp(tag: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{tag}] {message}")


def _empty_ai_payload() -> AiPayload:
    return AiPayload(
        game_summary="",
        address=None,
        metrics={
            "game_time": "?",
            "gold": "?",
            "hp_pct": "?",
            "mana_pct": "?",
            "level": "?",
            "kda": "?",
            "cs": "?",
            "event_signature": "none",
        },
    )


def _resolve_tts_rate_override(config: Config, backend: str, engine, text: str) -> int | None:
    mode = config.tts_playback_mode
    if mode not in {"fit_wait", "fit_continue"}:
        return None
    if backend != "windows" or not engine.supports_dynamic_rate():
        return None
    target_seconds = max(1.0, config.scheduler_interval * 0.9)
    base_rate = int(config.tts_config("windows").get("rate", 0))
    text_len = max(1, len(text.strip()))

    # Heuristic fit for short Chinese coaching lines on SAPI.
    estimated_chars_per_sec = max(1.6, 3.0 + base_rate * 0.18)
    desired_chars_per_sec = text_len / max(0.6, target_seconds - 0.4)
    desired_rate = round((desired_chars_per_sec - 3.0) / 0.18)
    # fit_* only speeds up when needed; it should never slow below the configured base rate.
    return max(-10, min(10, max(base_rate, desired_rate)))


def _is_overwolf_running() -> bool:
    try:
        result = shutil.which("powershell")
        shell = result or "powershell"
        cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('Overwolf.exe','OverwolfBrowser.exe') } | "
            "Select-Object -First 1 | ConvertTo-Json -Depth 2"
        )
        proc = os.popen(f'{shell} -NoProfile -Command "{cmd}"')
        output = proc.read().strip()
        proc.close()
        return bool(output and output != "null")
    except Exception:
        return False


def _try_start_overwolf(config: Config) -> None:
    if not config.overwolf_required:
        return
    if _is_overwolf_running():
        return

    method = str(config.get("launcher.overwolf.method", "auto")).strip().lower()
    path = str(config.get("launcher.overwolf.path", "")).strip()
    protocol = str(config.get("launcher.overwolf.protocol", "overwolf://")).strip() or "overwolf://"

    try:
        if method == "path" and path:
            subprocess.Popen([path], cwd=os.getcwd())
            print(f"[startup] Overwolf required, started via path: {path}")
            return
        if method == "protocol":
            os.startfile(protocol)
            print(f"[startup] Overwolf required, started via protocol: {protocol}")
            return

        auto_paths = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Overwolf", "OverwolfLauncher.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Overwolf", "OverwolfLauncher.exe"),
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "Overwolf", "OverwolfLauncher.exe"),
        ]
        for candidate in auto_paths:
            if candidate and os.path.exists(candidate):
                subprocess.Popen([candidate], cwd=os.getcwd())
                print(f"[startup] Overwolf required, started via auto path: {candidate}")
                return

        os.startfile(protocol)
        print(f"[startup] Overwolf required, started via fallback protocol: {protocol}")
    except Exception as exc:
        print(f"[startup] failed to start Overwolf: {exc}")


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


# ── Worker threads ─────────────────────────────────────────────────────────────

def ai_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tray: TrayIcon,
    capturer,
    qa_channel: QaChannel | None = None,
    debug: bool = False,
    debug_timing: bool = False,
):
    rule_engine = RuleEngine(enabled_plugin_ids=config.enabled_plugins, config=config)
    latest_image: bytes | None = None
    retry_after = 0.0
    context_window = ContextWindow(limit=config.decision_memory_size)
    _rule_repeat_count: dict[str, int] = {}
    _qa_mic_paused_for_tts = False
    _RULE_REPEAT_LIMIT = 3

    while not stop_event.is_set():
        # Always drain capture queue to keep latest screenshot buffered
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        # Honour backoff
        if retry_after > 0:
            print(f"[AI worker] waiting {retry_after:.0f}s...")
            stop_event.wait(timeout=retry_after)
            retry_after = 0.0
            if stop_event.is_set():
                break

        # Wait for next AI analysis slot
        stop_event.wait(timeout=config.scheduler_interval)
        if stop_event.is_set():
            break

        # Drain again after sleeping
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        try:
            cycle_started_at = time.perf_counter()
            tray.set_state(TrayIcon.STATE_BUSY)
            previous_plugin_id = rule_engine.bound_plugin_id
            active_context = rule_engine.discover_active_context()
            active_plugin_id = active_context.plugin.id if active_context else None
            if active_context and active_plugin_id != previous_plugin_id:
                print(
                    "[AI worker] matched plugin "
                    f"{active_context.plugin.display_name} ({active_plugin_id})"
                )
            rule_advice = rule_engine.evaluate_context(active_context) if active_context else None
            tts_busy_now = tts_busy_event.is_set()
            qa_question = None
            if qa_channel is not None and qa_channel.is_enabled(config):
                if tts_busy_now:
                    # TTS is playing — pause microphone capture and flush any already-buffered lines.
                    if not _qa_mic_paused_for_tts:
                        qa_channel.pause_microphone()
                        _qa_mic_paused_for_tts = True
                    qa_channel.flush_transcript()
                elif not _qa_hotkey_gate_open(config):
                    if _qa_mic_paused_for_tts:
                        qa_channel.resume_microphone()
                        _qa_mic_paused_for_tts = False
                    qa_channel.flush_transcript()
                else:
                    if _qa_mic_paused_for_tts:
                        qa_channel.resume_microphone()
                        _qa_mic_paused_for_tts = False
                    qa_question = qa_channel.poll_question()

            live_data = active_context.state.raw_data if active_context else None
            if live_data is None and qa_question is None and config.plugin_require_game(active_plugin_id):
                candidate_plugin_id = active_plugin_id or previous_plugin_id
                if candidate_plugin_id == "dialogue" and rule_engine.had_seen_activity():
                    print("[AI worker] waiting for dialogue input")
                elif rule_engine.had_seen_activity():
                    print("[AI worker] game over, skipping analysis")
                else:
                    print("[AI worker] not in game, skipping analysis")
                capturer.pause()
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue
            capturer.resume()
            payload = (
                active_context.plugin.build_ai_payload(
                    active_context.state,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                if active_context
                else _empty_ai_payload()
            )
            game_data = payload.game_summary
            metrics = payload.metrics
            address = payload.address
            if config.tts_playback_mode in {"wait", "fit_wait"} and tts_busy_event.is_set():
                tray.set_state(TrayIcon.STATE_RUNNING)
                print("[AI worker] waiting for TTS before next cycle")
                continue

            if qa_question is not None:
                _log_with_timestamp("QA", f"question={qa_question.text!r} source={qa_question.source_kind}")
                provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
                _search_t0 = time.perf_counter()
                web_search_docs = run_qa_web_search(
                    question=qa_question,
                    config=config,
                    active_context=active_context,
                )
                _search_elapsed_ms = (time.perf_counter() - _search_t0) * 1000
                _log_with_timestamp(
                    "QA search",
                    f"enabled={config.qa_web_search_enabled} "
                    f"mode={config.qa_web_search_mode} "
                    f"engine={config.qa_web_search_engine} "
                    f"docs={len(web_search_docs)} "
                    f"elapsed_ms={_search_elapsed_ms:.0f}",
                )
                for _i, _doc in enumerate(web_search_docs, 1):
                    _log_with_timestamp(
                        "QA search result",
                        f"[{_i}] site={_doc.domain} title={_doc.title!r} url={_doc.url}",
                    )
                prompt = build_qa_prompt(
                    question=qa_question,
                    system_prompt=config.qa_system_prompt,
                    active_context=active_context,
                    snapshots=context_window.items(),
                    rule_advice=rule_advice,
                    web_search_docs=web_search_docs,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                provider_started_at = time.perf_counter()
                text = provider.analyze(None, prompt)
                provider_elapsed_ms = (time.perf_counter() - provider_started_at) * 1000
                cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
                _log_with_timestamp(
                    "QA timing",
                    f"provider={config.ai_provider} "
                    f"provider_ms={provider_elapsed_ms:.0f} "
                    f"total_ms={cycle_elapsed_ms:.0f}",
                )
                if debug_timing:
                    print(
                        "[timing] "
                        "reason=qa "
                        "bridge_ms=0 "
                        f"provider_ms={provider_elapsed_ms:.0f} "
                        f"total_ms={cycle_elapsed_ms:.0f}"
                    )
                bus.put_advice(text)
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                context_window.add(
                    AnalysisSnapshot(
                        timestamp=datetime.datetime.now(),
                        game_summary=game_data,
                        address=address,
                        metrics=metrics,
                        bridge_facts={},
                        advice=text,
                        reason="qa",
                    )
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            allow_visual = bool(active_context and active_context.plugin.wants_visual_context(active_context.state))
            img = latest_image if config.capture_use_screenshot and allow_visual else None
            bridge_facts: dict[str, str] | None = None
            previous_snapshot = context_window.latest()
            decision_mode = config.decision_mode
            hybrid_threshold = int(config.rules_config.get("hybrid_priority_threshold", 85))
            if decision_mode == "rules":
                if not rule_advice:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    print("[Rules] no matching rule, skipping cycle")
                    continue
                rid = rule_advice.rule_id
                _rule_repeat_count[rid] = _rule_repeat_count.get(rid, 0) + 1
                # reset counts for rules that are no longer firing
                for key in list(_rule_repeat_count):
                    if key != rid:
                        _rule_repeat_count[key] = 0
                if _rule_repeat_count[rid] > _RULE_REPEAT_LIMIT:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    print(f"[Rules] suppressed repeat ({_rule_repeat_count[rid]}x): {rid}")
                    continue
                text = rule_advice.text
                if debug_timing:
                    cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
                    print(
                        "[timing] "
                        f"reason=rule:{rule_advice.rule_id} "
                        "bridge_ms=0 "
                        "provider_ms=0 "
                        f"total_ms={cycle_elapsed_ms:.0f}"
                    )
                bus.put_advice(text)
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                context_window.add(
                    AnalysisSnapshot(
                        timestamp=datetime.datetime.now(),
                        game_summary=game_data,
                        address=address,
                        metrics=metrics,
                        bridge_facts={},
                        advice=text,
                        reason=f"rule:{rule_advice.rule_id}",
                    )
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            if decision_mode == "hybrid" and rule_advice and rule_advice.priority >= hybrid_threshold:
                text = rule_advice.text
                if debug_timing:
                    cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
                    print(
                        "[timing] "
                        f"reason=hybrid_rule:{rule_advice.rule_id} "
                        "bridge_ms=0 "
                        "provider_ms=0 "
                        f"total_ms={cycle_elapsed_ms:.0f}"
                    )
                bus.put_advice(text)
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                context_window.add(
                    AnalysisSnapshot(
                        timestamp=datetime.datetime.now(),
                        game_summary=game_data,
                        address=address,
                        metrics=metrics,
                        bridge_facts={},
                        advice=text,
                        reason=f"hybrid_rule:{rule_advice.rule_id}",
                    )
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
            plan: AnalysisPlan = choose_analysis_plan(
                current_metrics=metrics,
                previous_snapshot=previous_snapshot,
                has_image=img is not None,
                now=datetime.datetime.now(),
                trigger_cfg=config.plugin_analysis_trigger(active_plugin_id),
            )
            if not plan.should_analyze:
                tray.set_state(TrayIcon.STATE_RUNNING)
                print(f"[AI worker] skipped stable cycle ({plan.reason})")
                continue

            # Vision bridge: uses raw screenshot regardless of main provider's use_screenshot.
            # Converts image to text description, then main provider receives text only.
            vb = config.vision_bridge
            bridge_elapsed_ms = 0.0
            if vb and latest_image is not None and plan.run_bridge:
                try:
                    vb_provider_name, vb_provider_cfg = config.vision_bridge_provider_config()
                    vb_provider = get_provider(vb_provider_name, vb_provider_cfg)
                    vb_prompt = (
                        vb.get("prompt")
                        or (
                            active_context.plugin.build_vision_prompt(
                                active_context.state,
                                detail=config.plugin_detail(active_plugin_id),
                            )
                            if active_context
                            else ""
                        )
                    )
                    if vb_prompt.strip():
                        bridge_started_at = time.perf_counter()
                        description = vb_provider.analyze(latest_image, vb_prompt)
                        bridge_elapsed_ms = (time.perf_counter() - bridge_started_at) * 1000
                        bridge_facts = parse_bridge_output(description)
                        img = None  # main provider always receives text only when bridge is active
                        print(f"[Vision bridge] {vb['provider']} → ok")
                except Exception as e:
                    img = None
                    print(f"[Vision bridge error] {e}")
            elif previous_snapshot is not None:
                bridge_facts = previous_snapshot.bridge_facts
            if vb:
                img = None

            prompt = (
                active_context.plugin.build_decision_prompt(
                    active_context.state,
                    system_prompt=config.plugin_system_prompt(active_plugin_id),
                    bridge_facts=bridge_facts,
                    snapshots=context_window.items(),
                    rule_hint=rule_advice.hint if rule_advice else None,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                if active_context
                else ""
            )

            if debug:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                os.makedirs("debug_captures", exist_ok=True)
                with open(f"debug_captures/{ts}_prompt.txt", "w", encoding="utf-8") as _f:
                    _f.write(f"[provider] {config.ai_provider}\n")
                    _f.write(f"[model] {config.ai_config(config.ai_provider).get('model', '')}\n")
                    _f.write(f"[trigger_reason] {plan.reason}\n")
                    _f.write(f"[screenshot] {'yes' if img else 'no'}\n")
                    if vb:
                        _f.write(f"[vision_bridge] {vb['provider']} → {bridge_facts.get('confidence', 'failed') if bridge_facts else 'failed'}\n")
                        _f.write(f"[vision_bridge_ms] {bridge_elapsed_ms:.0f}\n")
                    _f.write("\n")
                    _f.write(prompt)
            provider_started_at = time.perf_counter()
            text = provider.analyze(img, prompt)
            provider_elapsed_ms = (time.perf_counter() - provider_started_at) * 1000
            cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
            if debug_timing:
                print(
                    "[timing] "
                    f"reason={plan.reason} "
                    f"bridge_ms={bridge_elapsed_ms:.0f} "
                    f"provider_ms={provider_elapsed_ms:.0f} "
                    f"total_ms={cycle_elapsed_ms:.0f}"
                )
            bus.put_advice(text)
            bus.emit_advice(text)
            bridge.advice_ready.emit(text)
            context_window.add(
                AnalysisSnapshot(
                    timestamp=datetime.datetime.now(),
                    game_summary=game_data,
                    address=address,
                    metrics=metrics,
                    bridge_facts=bridge_facts or {},
                    advice=text,
                    reason=plan.reason,
                )
            )
            tray.set_state(TrayIcon.STATE_RUNNING)
        except Exception as e:
            msg = str(e)
            print(f"[AI worker error] {msg}")
            tray.set_state(TrayIcon.STATE_RUNNING)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                import re
                match = re.search(r"retryDelay.*?(\d+)s", msg)
                retry_after = int(match.group(1)) + 5 if match else 60
            elif "Connection error" in msg or "connect" in msg.lower():
                retry_after = 15
                print("[AI worker] connection failed, retrying in 15s — is Ollama running? (`ollama serve`)")


def tts_worker(bus: EventBus, config: Config, stop_event: threading.Event, busy_event: threading.Event):
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

    active_text: str | None = None
    active_started_at = 0.0

    while not stop_event.is_set():
        try:
            engine = get_engine()
            playback_mode = config.tts_playback_mode
            supports_interrupt = engine.supports_interrupt()

            if playback_mode == "interrupt" and supports_interrupt:
                next_text: str | None = None
                if active_text is not None:
                    if engine.is_busy():
                        busy_event.set()
                        try:
                            next_text = bus.get_latest_advice(timeout=0.1)
                        except queue.Empty:
                            continue
                        _log_with_timestamp("TTS", f"interrupt len={len(next_text)} text={next_text[:60]}")
                        engine.interrupt()
                        while engine.is_busy() and not stop_event.wait(timeout=0.02):
                            pass
                        elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                        _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f} interrupted=true")
                        active_text = None
                    else:
                        elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                        _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
                        active_text = None
                        busy_event.clear()
                        continue
                if next_text is None:
                    try:
                        next_text = bus.get_latest_advice(timeout=0.1)
                    except queue.Empty:
                        continue
                text = next_text
                active_text = text
                active_started_at = time.perf_counter()
                _log_with_timestamp("TTS", f"start len={len(text)} text={text[:60]}")
                busy_event.set()
                engine.start(text, rate_override=_resolve_tts_rate_override(config, current_backend, engine, text))
                continue

            try:
                text = bus.get_latest_advice(timeout=1.0)
            except queue.Empty:
                continue
            started_at = time.perf_counter()
            _log_with_timestamp("TTS", f"start len={len(text)} text={text[:60]}")
            busy_event.set()
            engine.speak(text, rate_override=_resolve_tts_rate_override(config, current_backend, engine, text))
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
        except Exception as e:
            print(f"[TTS worker error] {e}")
            busy_event.clear()
            active_text = None
        finally:
            if active_text is None and not stop_event.is_set():
                busy_event.clear()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOL Coach")
    parser.add_argument("--debug", action="store_true", help="save each screenshot to debug_captures/")
    parser.add_argument("--debug-timing", action="store_true", help="print bridge/provider timing for each analyzed cycle")
    parser.add_argument("--debug-stt", action="store_true", help="print microphone/STT diagnostic logs")
    args = parser.parse_args()
    os.environ["LOL_COACH_DEBUG_STT"] = "1" if args.debug_stt else "0"

    # Bootstrap config
    if not os.path.exists("config.yaml"):
        shutil.copy("config.example.yaml", "config.yaml")
        print("Created config.yaml from template — please add your API keys.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in tray

    config = Config("config.yaml")
    config._start_watcher()
    _try_start_overwolf(config)

    bus = EventBus()
    history = History("lol_coach.db")

    bridge = SignalBridge()
    stop_event = threading.Event()
    tts_busy_event = threading.Event()
    running = [False]
    qa_channel = QaChannel(config_path="config.yaml")

    # ── UI ────────────────────────────────────────────────────────────────────
    overlay = None
    if config.overlay.get("enabled", True):
        overlay = OverlayWindow(fade_after=config.overlay.get("fade_after", 8))
        overlay.move_to(config.overlay.get("x", 100), config.overlay.get("y", 100))

    window: MainWindow | None = None
    tray = TrayIcon("assets/icon.png")
    tray.show()

    def ensure_window() -> MainWindow:
        nonlocal window
        if window is None:
            window = MainWindow(config, history)
        return window

    # ── Signals ───────────────────────────────────────────────────────────────
    def on_advice(text: str):
        _log_with_timestamp("UI", f"display len={len(text)} text={text[:60]}")
        if overlay is not None:
            overlay.show_advice(text)
        if window is not None:
            window.on_advice(text)
            session_id = window.history_tab.get_current_session_id()
        else:
            session_id = None
        history.add_advice(text, "timer", session_id=session_id)

    bridge.advice_ready.connect(on_advice)

    # ── Capturer ──────────────────────────────────────────────────────────────
    capturer = Capturer(
        capture_queue=bus.capture_queue,
        interval=config.capture_interval,
        hotkey=config.capture_hotkey,
        region=config.capture_region,
        jpeg_quality=config.capture_jpeg_quality,
        monitor=config.capture_monitor,
        debug=args.debug,
    )

    # Register overlay toggle hotkey
    overlay_hotkey = config.overlay.get("toggle_hotkey", "")
    if overlay is not None and overlay_hotkey:
        try:
            import keyboard
            keyboard.add_hotkey(overlay_hotkey, lambda: overlay.setVisible(not overlay.isVisible()))
        except Exception:
            pass

    # ── Start / Pause ─────────────────────────────────────────────────────────
    ai_thread: threading.Thread | None = None
    tts_thread: threading.Thread | None = None

    def start_analysis():
        nonlocal ai_thread, tts_thread
        if running[0]:
            return
        running[0] = True
        stop_event.clear()
        capturer.start()
        ai_thread = threading.Thread(
            target=ai_worker,
            args=(bus, config, bridge, stop_event, tts_busy_event, tray, capturer, qa_channel),
            kwargs={"debug": args.debug, "debug_timing": args.debug_timing},
            daemon=True,
        )
        tts_thread = threading.Thread(target=tts_worker, args=(bus, config, stop_event, tts_busy_event), daemon=True)
        ai_thread.start()
        tts_thread.start()
        tray.set_state(TrayIcon.STATE_RUNNING)

    def pause_analysis():
        if not running[0]:
            return
        running[0] = False
        capturer.stop()
        stop_event.set()
        tray.set_state(TrayIcon.STATE_PAUSED)

    def toggle():
        if running[0]:
            pause_analysis()
        else:
            start_analysis()

    def open_window():
        ensure_window().show()
        ensure_window().raise_()
        ensure_window().activateWindow()

    tray.toggle_requested.connect(toggle)
    tray.open_window_requested.connect(open_window)
    tray.quit_requested.connect(lambda: (pause_analysis(), config._stop_watcher(), app.quit()))

    # ── Ctrl+C support ────────────────────────────────────────────────────────
    # PyQt blocks Python signal handling; a periodic QTimer lets the interpreter
    # check for SIGINT so Ctrl+C works from the terminal.
    def _handle_sigint(*_):
        print("\nCtrl+C received, exiting...")
        pause_analysis()
        config._stop_watcher()
        app.quit()

    signal.signal(signal.SIGINT, _handle_sigint)
    _sigint_timer = QTimer()
    _sigint_timer.start(500)
    _sigint_timer.timeout.connect(lambda: None)  # wake Python every 500ms

    # Auto-start
    if not config.start_minimized:
        open_window()
    start_analysis()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
