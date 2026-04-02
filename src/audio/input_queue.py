from __future__ import annotations

import queue
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class InputMessage:
    channel: str
    text: str
    speaker: str = "玩家"
    source_kind: str = "memory"
    created_at: datetime = field(default_factory=datetime.now)


class InputQueue:
    def __init__(self):
        self._queue: queue.Queue[InputMessage] = queue.Queue()

    def put(self, message: InputMessage) -> None:
        self._queue.put(message)

    def get_nowait(self) -> InputMessage | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def empty(self) -> bool:
        return self._queue.empty()
