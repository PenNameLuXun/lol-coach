import datetime as dt
import queue
import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class AdviceEvent:
    text: str
    source: str = "game_ai"
    priority: int = 100
    created_at: dt.datetime = field(default_factory=dt.datetime.now)
    expires_after_seconds: float | None = None
    dedupe_key: str | None = None
    interruptible: bool = True

    def is_expired(self, now: dt.datetime | None = None) -> bool:
        if self.expires_after_seconds is None:
            return False
        now = now or dt.datetime.now()
        age = (now - self.created_at).total_seconds()
        return age > self.expires_after_seconds


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _default_priority(source: str) -> int:
    mapping = {
        "qa_ack": 400,
        "qa": 300,
        "rule": 220,
        "hybrid_rule": 220,
        "game_ai": 100,
    }
    return mapping.get(source, 100)


def _default_expiry_seconds(source: str) -> float | None:
    mapping = {
        "qa_ack": 3.0,
        "qa": 30.0,
        "rule": 8.0,
        "hybrid_rule": 8.0,
        "game_ai": 6.0,
    }
    return mapping.get(source, 10.0)


class EventBus:
    """Thread-safe queues for image frames and advice text/events."""

    def __init__(self):
        self._capture_q: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._advice_q: queue.Queue[AdviceEvent] = queue.Queue(maxsize=10)
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

    def put_advice(
        self,
        text: str,
        *,
        source: str = "game_ai",
        priority: int | None = None,
        expires_after_seconds: float | None = None,
        dedupe_key: str | None = None,
        interruptible: bool = True,
    ) -> AdviceEvent:
        event = AdviceEvent(
            text=text,
            source=source,
            priority=_default_priority(source) if priority is None else priority,
            expires_after_seconds=_default_expiry_seconds(source)
            if expires_after_seconds is None
            else expires_after_seconds,
            dedupe_key=dedupe_key,
            interruptible=interruptible,
        )
        self._put_advice_event(event)
        return event

    def _put_advice_event(self, event: AdviceEvent) -> None:
        try:
            self._advice_q.put_nowait(event)
        except queue.Full:
            pending = self._drain_advice_queue()
            pending.append(event)
            kept = self._reduce_events(pending, limit=self._advice_q.maxsize)
            for item in kept:
                self._advice_q.put_nowait(item)

    def get_advice_event(self, timeout: float = 1.0) -> AdviceEvent:
        deadline = dt.datetime.now() + dt.timedelta(seconds=timeout)
        while True:
            remaining = max(0.0, (deadline - dt.datetime.now()).total_seconds())
            if remaining <= 0:
                raise queue.Empty
            first = self._advice_q.get(timeout=remaining)
            batch = [first] + self._drain_advice_queue()
            reduced = self._reduce_events(batch)
            if not reduced:
                continue
            return self._select_event(reduced)

    def get_advice(self, timeout: float = 1.0) -> str:
        return self.get_advice_event(timeout=timeout).text

    def get_latest_advice_event(self, timeout: float = 1.0) -> AdviceEvent:
        return self.get_advice_event(timeout=timeout)

    def get_latest_advice(self, timeout: float = 1.0) -> str:
        return self.get_advice_event(timeout=timeout).text

    def _drain_advice_queue(self) -> list[AdviceEvent]:
        items: list[AdviceEvent] = []
        try:
            while True:
                items.append(self._advice_q.get_nowait())
        except queue.Empty:
            pass
        return items

    def _reduce_events(self, events: list[AdviceEvent], limit: int | None = None) -> list[AdviceEvent]:
        now = dt.datetime.now()
        deduped: dict[str, AdviceEvent] = {}
        passthrough: list[AdviceEvent] = []
        for event in events:
            if event.is_expired(now):
                continue
            if not event.text.strip():
                continue
            key = event.dedupe_key
            if not key:
                passthrough.append(event)
                continue
            current = deduped.get(key)
            if current is None or self._event_rank(event) >= self._event_rank(current):
                deduped[key] = event

        reduced = list(deduped.values()) + passthrough
        reduced.sort(key=self._event_rank, reverse=True)
        if limit is not None:
            reduced = reduced[:limit]
        return reduced

    def _select_event(self, events: list[AdviceEvent]) -> AdviceEvent:
        return max(events, key=self._event_rank)

    def _event_rank(self, event: AdviceEvent) -> tuple[int, float]:
        return (int(event.priority), event.created_at.timestamp())

    # ── listener pattern (for non-Qt consumers) ───────────────────────────────

    def add_advice_listener(self, callback: Callable[[str], None]):
        self._advice_listeners.append(callback)

    def emit_advice(self, text: str):
        for cb in self._advice_listeners:
            cb(text)

    # ── public queue accessors ────────────────────────────────────────────────

    @property
    def capture_queue(self) -> queue.Queue:
        return self._capture_q
