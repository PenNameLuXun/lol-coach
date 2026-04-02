from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AudioSegment:
    pcm_bytes: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2


class SpeechSegmenter:
    def __init__(self, silence_ms: int = 1000):
        self._silence_ms = max(200, int(silence_ms))

    @property
    def silence_ms(self) -> int:
        return self._silence_ms

    def reset(self) -> None:
        return None
