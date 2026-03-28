import queue
from typing import Callable


class EventBus:
    """Thread-safe queues for image frames and advice text.

    capture_queue: bytes (JPEG image)
    advice_queue:  str   (advice text)

    Listeners registered via add_advice_listener() are called synchronously
    from whatever thread calls emit_advice(). UI components must connect via
    Qt Signals instead; this mechanism is for non-UI consumers (TTS, history).
    """

    def __init__(self):
        self._capture_q: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._advice_q: queue.Queue[str] = queue.Queue(maxsize=10)
        self._advice_listeners: list[Callable[[str], None]] = []

    # ── capture queue ─────────────────────────────────────────────────────────

    def put_capture(self, image_bytes: bytes):
        """Non-blocking put; drops oldest frame if queue is full."""
        try:
            self._capture_q.put_nowait(image_bytes)
        except queue.Full:
            try:
                self._capture_q.get_nowait()
            except queue.Empty:
                pass
            self._capture_q.put_nowait(image_bytes)

    def get_capture(self, timeout: float = 1.0) -> bytes:
        return self._capture_q.get(timeout=timeout)

    def peek_latest_capture(self) -> bytes | None:
        """Non-blocking: drain queue and return the latest frame, or None if empty."""
        latest = None
        try:
            while True:
                latest = self._capture_q.get_nowait()
        except queue.Empty:
            pass
        return latest

    # ── advice queue ──────────────────────────────────────────────────────────

    def put_advice(self, text: str):
        self._advice_q.put_nowait(text)

    def get_advice(self, timeout: float = 1.0) -> str:
        return self._advice_q.get(timeout=timeout)

    def get_latest_advice(self, timeout: float = 1.0) -> str:
        """Block until advice is available, then drain the queue and return only the latest item."""
        text = self._advice_q.get(timeout=timeout)
        try:
            while True:
                text = self._advice_q.get_nowait()
        except queue.Empty:
            pass
        return text

    # ── listener pattern (for non-Qt consumers) ───────────────────────────────

    def add_advice_listener(self, callback: Callable[[str], None]):
        self._advice_listeners.append(callback)

    def emit_advice(self, text: str):
        """Call all registered listeners with the advice text."""
        for cb in self._advice_listeners:
            cb(text)

    # ── public queue accessors ────────────────────────────────────────────────

    @property
    def capture_queue(self) -> queue.Queue:
        return self._capture_q
