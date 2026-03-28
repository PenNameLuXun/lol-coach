import asyncio
import io
import subprocess
import tempfile
from abc import ABC, abstractmethod

import pyttsx3
import openai


class BaseTTS(ABC):
    @abstractmethod
    def speak(self, text: str): ...

    def interrupt(self): ...  # optional: stop current playback


class WindowsTTS(BaseTTS):
    def __init__(self, rate: int, volume: float):
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)

    def speak(self, text: str):
        self._engine.say(text)
        self._engine.runAndWait()

    def interrupt(self):
        self._engine.stop()


class EdgeTTS(BaseTTS):
    def __init__(self, voice: str):
        self._voice = voice

    def speak(self, text: str):
        asyncio.run(self._async_speak(text))

    async def _async_speak(self, text: str):
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        communicate = edge_tts.Communicate(text, self._voice)
        await communicate.save(tmp_path)
        subprocess.run(["powershell", "-c", f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()'],
                       capture_output=True)


class OpenAITTS(BaseTTS):
    def __init__(self, api_key: str, voice: str, model: str):
        self._client = openai.OpenAI(api_key=api_key)
        self._voice = voice
        self._model = model

    def speak(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
        )
        response.stream_to_file(tmp_path)
        subprocess.run(["powershell", "-c", f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()'],
                       capture_output=True)


def get_tts_engine(backend: str, cfg: dict) -> BaseTTS:
    if backend == "windows":
        return WindowsTTS(rate=cfg.get("rate", 180), volume=cfg.get("volume", 1.0))
    if backend == "edge":
        return EdgeTTS(voice=cfg.get("voice", "zh-CN-XiaoxiaoNeural"))
    if backend == "openai":
        return OpenAITTS(api_key=cfg["api_key"], voice=cfg.get("voice", "alloy"), model=cfg.get("model", "tts-1"))
    raise ValueError(f"Unknown TTS backend: {backend}")
