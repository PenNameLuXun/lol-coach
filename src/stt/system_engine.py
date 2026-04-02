from __future__ import annotations


class NullSttEngine:
    def __init__(self, language: str = "zh-CN"):
        self._language = language

    def is_supported(self) -> bool:
        return False

    def transcribe(self, wav_bytes: bytes) -> str | None:
        return None
