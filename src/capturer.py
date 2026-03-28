import io
import queue
import threading

import mss
import mss.tools
from PIL import Image


class Capturer:
    """Captures screenshots and puts JPEG bytes into capture_queue.

    Two trigger modes (can run simultaneously):
    - Timer: captures every `interval` seconds when interval > 0
    - Hotkey: calls capture_once() when global hotkey pressed (registered externally)
    """

    def __init__(
        self,
        capture_queue: queue.Queue,
        interval: int,
        hotkey: str,
        region: str,
        jpeg_quality: int,
    ):
        self._queue = capture_queue
        self._interval = interval
        self._hotkey = hotkey
        self._region = region
        self._jpeg_quality = jpeg_quality
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._hotkey_registered = False

    def start(self):
        """Start timer-based capture thread and register hotkey."""
        if self._interval > 0:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._timer_loop, daemon=True)
            self._thread.start()
        if self._hotkey:
            self._register_hotkey()

    def stop(self):
        self._stop_event.set()
        if self._hotkey_registered:
            self._unregister_hotkey()
        if self._thread:
            self._thread.join(timeout=self._interval + 2)

    def capture_once(self):
        """Take one screenshot and put JPEG bytes into the queue."""
        jpeg = self._take_screenshot()
        try:
            self._queue.put_nowait(jpeg)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(jpeg)

    def _timer_loop(self):
        while not self._stop_event.wait(timeout=self._interval):
            self.capture_once()

    def _take_screenshot(self) -> bytes:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # full screen (index 0 = all monitors combined)
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self._jpeg_quality)
            return buf.getvalue()

    def _register_hotkey(self):
        try:
            import keyboard
            keyboard.add_hotkey(self._hotkey, self.capture_once)
            self._hotkey_registered = True
        except Exception:
            pass  # keyboard may require elevated permissions

    def _unregister_hotkey(self):
        try:
            import keyboard
            keyboard.remove_hotkey(self._hotkey)
        except Exception:
            pass
