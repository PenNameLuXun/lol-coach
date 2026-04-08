"""LOL Coach — entry point.

Wires all components together:
- Config -> loaded from config.yaml (copied from config.example.yaml on first run)
- EventBus -> shared queues between threads
- Capturer -> screenshot daemon thread
- AI worker thread -> consumes capture_queue, produces advice
- TTS worker thread -> consumes advice_queue
- History -> SQLite, accessed from main thread via signals
- UI -> MainWindow (hidden), TrayIcon, OverlayWindow
"""

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from src.config import Config
from src.event_bus import EventBus
from src.history import History
from src.capturer import Capturer
from src.qa_channel import QaChannel
from src.ui.knowledge_window import KnowledgeWindow
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow
from src.workers import (
    SignalBridge,
    QaRuntimeContext,
    log_with_timestamp,
    ai_worker,
    tts_worker,
    qa_worker,
)


# ── Logging setup ────────────────────────────────────────────────────────────

def _setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(message)s"
    logging.basicConfig(level=level, format=fmt, force=True)
    # Quiet noisy third-party loggers
    for name in ("urllib3", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ── Startup helpers ──────────────────────────────────────────────────────────

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


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOL Coach")
    parser.add_argument("--debug", action="store_true", help="save each screenshot to debug_captures/")
    parser.add_argument("--debug-timing", action="store_true", help="print bridge/provider timing for each analyzed cycle")
    parser.add_argument("--debug-stt", action="store_true", help="print microphone/STT diagnostic logs")
    parser.add_argument("--debug-fake-lol-info", action="store_true", help="pretend a fake LoL match is active for UI/web-knowledge testing")
    parser.add_argument("--debug-fake-tft-info", action="store_true", help="pretend a fake TFT match is active for UI/web-knowledge testing")
    args = parser.parse_args()

    _setup_logging(debug=args.debug)
    os.environ["LOL_COACH_DEBUG_STT"] = "1" if args.debug_stt else "0"

    # Bootstrap config
    if not os.path.exists("config.yaml"):
        shutil.copy("config.example.yaml", "config.yaml")
        print("Created config.yaml from template — please add your API keys.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = Config("config.yaml")
    setattr(config, "_debug_timing", bool(args.debug_timing))
    config._start_watcher()
    _try_start_overwolf(config)

    bus = EventBus()
    history = History("lol_coach.db")

    bridge = SignalBridge()
    stop_event = threading.Event()
    tts_busy_event = threading.Event()
    tts_interrupt_event = threading.Event()
    running = [False]
    qa_channel_instance = QaChannel(config_path="config.yaml")
    qa_runtime = QaRuntimeContext()

    # ── UI ────────────────────────────────────────────────────────────────
    overlay = None
    knowledge_window = None
    if config.overlay.get("enabled", True):
        overlay = OverlayWindow(fade_after=config.overlay.get("fade_after", 8))
        overlay.move_to(config.overlay.get("x", 100), config.overlay.get("y", 100))

    if config.web_knowledge_enabled:
        knowledge_window = KnowledgeWindow(
            width=config.web_knowledge_window_width,
            height=config.web_knowledge_window_height,
            size_mode=config.web_knowledge_window_size_mode,
        )
        screens = app.screens()
        if len(screens) > 1:
            geo = screens[1].availableGeometry()
            knowledge_window.move(geo.x(), geo.y())

    window: MainWindow | None = None
    tray = TrayIcon("assets/icon.png")
    tray.show()

    def ensure_window() -> MainWindow:
        nonlocal window
        if window is None:
            window = MainWindow(config, history)
        return window

    # ── Signals ───────────────────────────────────────────────────────────
    def on_advice(text: str):
        log_with_timestamp("UI", f"display len={len(text)} text={text[:60]}")
        if overlay is not None:
            overlay.show_advice(text)
        if window is not None:
            window.on_advice(text)
            session_id = window.history_tab.get_current_session_id()
        else:
            session_id = None
        history.add_advice(text, "timer", session_id=session_id)

    bridge.advice_ready.connect(on_advice)

    def on_knowledge(payload):
        if knowledge_window is None:
            return
        screens = app.screens()
        auto_show = len(screens) > 1 or config.web_knowledge_always_visible
        if not isinstance(payload, dict):
            knowledge_window.update_bundle(payload)
            if payload is not None and auto_show and not knowledge_window.is_dismissed and not knowledge_window.isVisible():
                knowledge_window.show()
            return
        plugin = payload.get("plugin")
        state = payload.get("state")
        bundle = payload.get("bundle")
        if plugin is None or bundle is None:
            knowledge_window.update_bundle(bundle)
            if bundle is not None and auto_show and not knowledge_window.is_dismissed and not knowledge_window.isVisible():
                knowledge_window.show()
            return
        populate = getattr(plugin, "populate_web_knowledge_window", None)
        if callable(populate):
            handled = bool(populate(knowledge_window, bundle, state, config))
            if handled:
                if auto_show and not knowledge_window.is_dismissed and not knowledge_window.isVisible():
                    knowledge_window.show()
                return
        knowledge_window.update_bundle(bundle)
        if bundle is not None and auto_show and not knowledge_window.is_dismissed and not knowledge_window.isVisible():
            knowledge_window.show()

    bridge.knowledge_ready.connect(on_knowledge)

    # ── Capturer ──────────────────────────────────────────────────────────
    capturer = Capturer(
        capture_queue=bus.capture_queue,
        interval=config.capture_interval,
        hotkey=config.capture_hotkey,
        region=config.capture_region,
        jpeg_quality=config.capture_jpeg_quality,
        monitor=config.capture_monitor,
        debug=args.debug,
    )

    overlay_hotkey = config.overlay.get("toggle_hotkey", "")
    if overlay is not None and overlay_hotkey:
        try:
            import keyboard
            keyboard.add_hotkey(overlay_hotkey, lambda: overlay.setVisible(not overlay.isVisible()))
        except Exception:
            pass

    # ── Start / Pause ─────────────────────────────────────────────────────
    ai_thread: threading.Thread | None = None
    qa_thread: threading.Thread | None = None
    tts_thread: threading.Thread | None = None

    def start_analysis():
        nonlocal ai_thread, qa_thread, tts_thread
        if running[0]:
            return
        running[0] = True
        stop_event.clear()
        tts_interrupt_event.clear()
        capturer.start()
        ai_thread = threading.Thread(
            target=ai_worker,
            args=(bus, config, bridge, stop_event, tts_busy_event, tray, capturer, qa_runtime, qa_channel_instance),
            kwargs={
                "debug": args.debug,
                "debug_timing": args.debug_timing,
                "debug_fake_lol_info": args.debug_fake_lol_info,
                "debug_fake_tft_info": args.debug_fake_tft_info,
            },
            daemon=True,
        )
        qa_thread = threading.Thread(
            target=qa_worker,
            args=(bus, config, bridge, stop_event, tts_busy_event, tts_interrupt_event, qa_channel_instance, qa_runtime),
            kwargs={"debug_timing": args.debug_timing},
            daemon=True,
        )
        tts_thread = threading.Thread(
            target=tts_worker,
            args=(bus, config, stop_event, tts_busy_event, tts_interrupt_event),
            daemon=True,
        )
        ai_thread.start()
        qa_thread.start()
        tts_thread.start()
        tray.set_state(TrayIcon.STATE_RUNNING)

    def pause_analysis():
        if not running[0]:
            qa_channel_instance.stop()
            return
        running[0] = False
        capturer.stop()
        stop_event.set()
        qa_channel_instance.stop()
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

    # ── Ctrl+C support ────────────────────────────────────────────────────
    def _handle_sigint(*_):
        print("\nCtrl+C received, exiting...")
        pause_analysis()
        config._stop_watcher()
        app.quit()

    signal.signal(signal.SIGINT, _handle_sigint)
    if knowledge_window is not None and len(app.screens()) <= 1:
        _knowledge_hotkey_timer = QTimer()
        _knowledge_hotkey_timer.start(120)

        def _update_knowledge_visibility():
            hotkey = config.web_knowledge_hotkey
            always_visible = config.web_knowledge_always_visible
            visible = False
            try:
                import keyboard
                visible = bool(hotkey and keyboard.is_pressed(hotkey))
            except Exception:
                visible = False

            if always_visible:
                if knowledge_window.is_dismissed:
                    if visible:
                        if not knowledge_window.has_content:
                            knowledge_window.show_loading()
                        knowledge_window.revive()
                elif knowledge_window.has_content and not knowledge_window.isVisible():
                    knowledge_window.show()
                return

            if visible and not knowledge_window.isVisible():
                if not knowledge_window.has_content:
                    knowledge_window.show_loading()
                knowledge_window.revive()
            elif not visible and knowledge_window.isVisible():
                knowledge_window.hide()

        _knowledge_hotkey_timer.timeout.connect(_update_knowledge_visibility)

    _sigint_timer = QTimer()
    _sigint_timer.start(500)
    _sigint_timer.timeout.connect(lambda: None)

    # Auto-start
    if not config.start_minimized:
        open_window()
    start_analysis()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
