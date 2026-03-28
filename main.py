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
import queue
import shutil
import signal
import sys
import threading
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from src.config import Config
from src.event_bus import EventBus
from src.history import History
from src.capturer import Capturer
from src.ai_provider import get_provider
from src.tts_engine import get_tts_engine
from src.lol_client import LolClient
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow


# ── Qt Signal bridge from worker threads to UI ────────────────────────────────

class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)


# ── Worker threads ─────────────────────────────────────────────────────────────

def ai_worker(bus: EventBus, config: Config, bridge: SignalBridge, stop_event: threading.Event, tray: TrayIcon):
    retry_after = 0.0  # seconds to wait before next request (rate-limit backoff)
    lol = LolClient()
    while not stop_event.is_set():
        try:
            image_bytes = bus.get_capture(timeout=1.0)
        except queue.Empty:
            continue
        # honour rate-limit backoff
        if retry_after > 0:
            import time
            print(f"[AI worker] rate limited, waiting {retry_after:.0f}s...")
            stop_event.wait(timeout=retry_after)
            retry_after = 0.0
            if stop_event.is_set():
                break
        try:
            tray.set_state(TrayIcon.STATE_BUSY)
            provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
            prompt = config.system_prompt
            game_data = lol.get_game_summary(detail=config.lol_client_detail)
            if game_data is None and lol.last_seen_in_game:
                print("[AI worker] game over, skipping analysis")
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue
            address = lol.get_player_address(config.lol_client_address_by)
            if address:
                prompt = f'{prompt}\n请用"{address}"称呼玩家。'
            if game_data:
                prompt = f"{prompt}\n\n当前游戏数据：{game_data}"
            img = image_bytes if config.capture_use_screenshot else None
            text = provider.analyze(img, prompt)
            bus.put_advice(text)
            bus.emit_advice(text)
            bridge.advice_ready.emit(text)
            tray.set_state(TrayIcon.STATE_RUNNING)
        except Exception as e:
            msg = str(e)
            print(f"[AI worker error] {msg}")
            tray.set_state(TrayIcon.STATE_RUNNING)
            # back off on 429 rate-limit errors
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                import re
                match = re.search(r"retryDelay.*?(\d+)s", msg)
                retry_after = int(match.group(1)) + 5 if match else 60
            # back off on connection errors (e.g. Ollama not running)
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
        ai_thread = threading.Thread(target=ai_worker, args=(bus, config, bridge, stop_event, tray), daemon=True)
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
