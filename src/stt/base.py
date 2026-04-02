from __future__ import annotations

from typing import Protocol


class SttEngine(Protocol):
    def is_supported(self) -> bool:
        ...

    def transcribe(self, wav_bytes: bytes) -> str | None:
        ...
