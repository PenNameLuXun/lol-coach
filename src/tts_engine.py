import asyncio
import datetime
import tempfile
import time
from abc import ABC, abstractmethod

import openai


class BaseTTS(ABC):
    @abstractmethod
    def speak(self, text: str, rate_override=None): ...

    def interrupt(self): ...  # optional: stop current playback

    def supports_interrupt(self) -> bool:
        return False

    def supports_dynamic_rate(self) -> bool:
        return False

    def start(self, text: str, rate_override=None):
        self.speak(text, rate_override=rate_override)

    def is_busy(self) -> bool:
        return False


def _tts_log(stage: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [TTS:{stage}] {message}")


class WindowsTTS(BaseTTS):
    _ASYNC_FLAG = 1

    def __init__(self, rate: int, volume: float):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        self._pythoncom = pythoncom
        self._voice = win32com.client.Dispatch("SAPI.SpVoice")
        self._base_rate = self._normalize_rate(rate)
        # SAPI volume is 0-100; keep accepting 0.0-1.0 in config.
        self._voice.Rate = self._base_rate
        self._voice.Volume = max(0, min(100, int(volume * 100)))

    @staticmethod
    def _normalize_rate(rate: int) -> int:
        return max(-10, min(10, int(rate)))

    def speak(self, text: str, rate_override=None):
        self.start(text, rate_override=rate_override)
        started_at = time.perf_counter()
        while self.is_busy():
            time.sleep(0.05)
        _tts_log("windows", f"engine_end elapsed_ms={(time.perf_counter() - started_at) * 1000:.0f}")

    def start(self, text: str, rate_override=None):
        applied_rate = self._base_rate if rate_override is None else self._normalize_rate(rate_override)
        self._voice.Rate = applied_rate
        _tts_log("windows", f"engine_start len={len(text)} rate={applied_rate}")
        self._voice.Speak(text, self._ASYNC_FLAG)

    def supports_interrupt(self) -> bool:
        return True

    def supports_dynamic_rate(self) -> bool:
        return True

    def is_busy(self) -> bool:
        return not bool(self._voice.WaitUntilDone(0))

    def interrupt(self):
        # 2 = SVSFPurgeBeforeSpeak
        self._voice.Speak("", 2)

    def __del__(self):
        try:
            self._pythoncom.CoUninitialize()
        except Exception:
            pass


class EdgeTTS(BaseTTS):
    def __init__(self, voice: str, rate: str = "+0%"):
        self._voice = voice
        self._rate = rate
        self._mixer_inited = False

    def _ensure_mixer(self):
        if not self._mixer_inited:
            import pygame
            pygame.mixer.init()
            self._mixer_inited = True

    def speak(self, text: str, rate_override=None):
        asyncio.run(self._async_speak(text))

    async def _async_speak(self, text: str):
        import edge_tts
        import pygame
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        synth_started_at = time.perf_counter()
        _tts_log("edge", f"synth_start len={len(text)} path={tmp_path}")
        communicate = edge_tts.Communicate(text, self._voice, rate=self._rate)
        await communicate.save(tmp_path)
        synth_elapsed_ms = (time.perf_counter() - synth_started_at) * 1000
        _tts_log("edge", f"synth_end elapsed_ms={synth_elapsed_ms:.0f}")
        play_started_at = time.perf_counter()
        self._ensure_mixer()
        pygame.mixer.music.load(tmp_path)
        _tts_log("edge", "play_start")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        _tts_log("edge", f"play_end elapsed_ms={(time.perf_counter() - play_started_at) * 1000:.0f}")


class OpenAITTS(BaseTTS):
    def __init__(self, api_key: str, voice: str, model: str):
        self._client = openai.OpenAI(api_key=api_key)
        self._voice = voice
        self._model = model
        self._mixer_inited = False

    def _ensure_mixer(self):
        if not self._mixer_inited:
            import pygame
            pygame.mixer.init()
            self._mixer_inited = True

    def speak(self, text: str, rate_override=None):
        import pygame
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        synth_started_at = time.perf_counter()
        _tts_log("openai", f"synth_start len={len(text)} path={tmp_path}")
        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
        )
        response.stream_to_file(tmp_path)
        synth_elapsed_ms = (time.perf_counter() - synth_started_at) * 1000
        _tts_log("openai", f"synth_end elapsed_ms={synth_elapsed_ms:.0f}")
        play_started_at = time.perf_counter()
        self._ensure_mixer()
        pygame.mixer.music.load(tmp_path)
        _tts_log("openai", "play_start")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        _tts_log("openai", f"play_end elapsed_ms={(time.perf_counter() - play_started_at) * 1000:.0f}")


def get_tts_engine(backend: str, cfg: dict) -> BaseTTS:
    if backend == "windows":
        return WindowsTTS(rate=cfg.get("rate", 0), volume=cfg.get("volume", 1.0))
    if backend == "edge":
        return EdgeTTS(voice=cfg.get("voice", "zh-CN-XiaoxiaoNeural"), rate=cfg.get("rate", "+0%"))
    if backend == "openai":
        return OpenAITTS(api_key=cfg["api_key"], voice=cfg.get("voice", "alloy"), model=cfg.get("model", "tts-1"))
    raise ValueError(f"Unknown TTS backend: {backend}")
