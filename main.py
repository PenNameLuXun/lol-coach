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
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow


# ── Qt Signal bridge from worker threads to UI ────────────────────────────────

class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)


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


# ── Worker threads ─────────────────────────────────────────────────────────────

def ai_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tray: TrayIcon,
    capturer,
    debug: bool = False,
    debug_timing: bool = False,
):
    rule_engine = RuleEngine(enabled_plugin_ids=config.enabled_plugins)
    latest_image: bytes | None = None
    retry_after = 0.0
    context_window = ContextWindow(limit=config.decision_memory_size)

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
        stop_event.wait(timeout=config.ai_interval)
        if stop_event.is_set():
            break

        # Drain again after sleeping
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        try:
            cycle_started_at = time.perf_counter()
            tray.set_state(TrayIcon.STATE_BUSY)
            active_context = rule_engine.discover_active_context()
            live_data = active_context.state.raw_data if active_context else None
            if live_data is None and config.lol_client_require_game:
                if rule_engine.had_seen_activity():
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
                    detail=config.lol_client_detail,
                    address_by=config.lol_client_address_by,
                )
                if active_context
                else _empty_ai_payload()
            )
            game_data = payload.game_summary
            metrics = payload.metrics
            address = payload.address
            img = latest_image if config.capture_use_screenshot else None
            bridge_facts: dict[str, str] | None = None
            previous_snapshot = context_window.latest()
            rule_advice = rule_engine.evaluate_context(active_context) if active_context else None
            decision_mode = config.decision_mode
            hybrid_threshold = int(config.rules_config.get("hybrid_priority_threshold", 85))
            if decision_mode == "rules":
                if not rule_advice:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    print("[Rules] no matching rule, skipping cycle")
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
                trigger_cfg=config.analysis_trigger,
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
                                detail=config.lol_client_detail,
                            )
                            if active_context
                            else ""
                        )
                    )
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
                    system_prompt=config.system_prompt,
                    bridge_facts=bridge_facts,
                    snapshots=context_window.items(),
                    rule_hint=rule_advice.hint if rule_advice else None,
                    detail=config.lol_client_detail,
                    address_by=config.lol_client_address_by,
                )
                if active_context
                else ""
            )

            if debug:
                import datetime
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


def tts_worker(bus: EventBus, config: Config, stop_event: threading.Event):
    current_engine = None

    def get_engine():
        return get_tts_engine(config.tts_backend, config.tts_config(config.tts_backend))

    while not stop_event.is_set():
        try:
            text = bus.get_latest_advice(timeout=1.0)
        except queue.Empty:
            continue
        try:
            engine = get_engine()
            if config.tts_interrupt and current_engine:
                current_engine.interrupt()
            current_engine = engine
            engine.speak(text)
        except Exception as e:
            print(f"[TTS worker error] {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOL Coach")
    parser.add_argument("--debug", action="store_true", help="save each screenshot to debug_captures/")
    parser.add_argument("--debug-timing", action="store_true", help="print bridge/provider timing for each analyzed cycle")
    args = parser.parse_args()

    # Bootstrap config
    if not os.path.exists("config.yaml"):
        shutil.copy("config.example.yaml", "config.yaml")
        print("Created config.yaml from template — please add your API keys.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in tray

    config = Config("config.yaml")
    config._start_watcher()

    bus = EventBus()
    history = History("lol_coach.db")

    bridge = SignalBridge()
    stop_event = threading.Event()
    running = [False]

    # ── UI ────────────────────────────────────────────────────────────────────
    overlay = OverlayWindow(fade_after=config.overlay.get("fade_after", 8))
    overlay.move_to(config.overlay.get("x", 100), config.overlay.get("y", 100))

    window = MainWindow(config, history)
    tray = TrayIcon("assets/icon.png")
    tray.show()

    # ── Signals ───────────────────────────────────────────────────────────────
    def on_advice(text: str):
        overlay.show_advice(text)
        window.on_advice(text)
        session_id = window.history_tab.get_current_session_id()
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
    if overlay_hotkey:
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
            args=(bus, config, bridge, stop_event, tray, capturer),
            kwargs={"debug": args.debug, "debug_timing": args.debug_timing},
            daemon=True,
        )
        tts_thread = threading.Thread(target=tts_worker, args=(bus, config, stop_event), daemon=True)
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

    tray.toggle_requested.connect(toggle)
    tray.open_window_requested.connect(window.show)
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
        window.show()
    start_analysis()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
