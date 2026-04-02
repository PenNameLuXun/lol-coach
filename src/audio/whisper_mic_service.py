"""Microphone capture + Whisper transcription service.

Uses sounddevice for audio capture and faster-whisper for STT.
Runs in a background thread, appends recognized text to a transcript file.
"""
from __future__ import annotations

import io
import os
import threading
import time
import wave
from pathlib import Path


def _debug() -> bool:
    return os.environ.get("LOL_COACH_DEBUG_STT", "").strip().lower() in {"1", "true", "yes"}


class WhisperMicService:
    """Records from the default microphone in chunks, detects silence,
    sends completed utterances to Whisper, appends results to transcript_path."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_FRAMES = 1024          # frames per sounddevice callback
    SILENCE_THRESHOLD = 0.01     # RMS threshold below which we consider silence
    MIN_SPEECH_SECONDS = 0.4     # ignore clips shorter than this

    def __init__(
        self,
        transcript_path: Path,
        language: str = "zh",
        silence_ms: int = 1000,
        model: str = "base",
        preloaded_model=None,
    ):
        self._transcript_path = transcript_path
        self._language = language
        self._silence_ms = silence_ms
        self._model_name = model
        self._model = preloaded_model  # accept pre-loaded model to avoid Qt/OpenMP conflict
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False

    def is_supported(self) -> bool:
        try:
            import sounddevice  # noqa: F401
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def start(self) -> bool:
        if not self.is_supported():
            if _debug():
                print("[WhisperMic] sounddevice or faster-whisper not installed")
            return False
        self._transcript_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._transcript_path.exists():
            self._transcript_path.write_text("", encoding="utf-8")
        # Load model in the calling thread (main/Qt thread) before spawning the
        # background thread — avoids OpenMP init crash inside a daemon thread.
        try:
            self._load_model()
        except Exception as e:
            print(f"[WhisperMic] failed to load model: {e}")
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="whisper-mic")
        self._thread.start()
        self._running = True
        if _debug():
            print(f"[WhisperMic] started language={self._language} model={self._model_name} silence_ms={self._silence_ms}")
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if _debug():
            print("[WhisperMic] stopped")

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def _load_model(self):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        device = "cpu"
        compute = "int8"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                compute = "float16"
        except ImportError:
            pass
        if _debug():
            print(f"[WhisperMic] loading model={self._model_name} device={device}")
        self._model = WhisperModel(
            self._model_name,
            device=device,
            compute_type=compute,
            cpu_threads=1,
            local_files_only=True,
        )
        if _debug():
            print("[WhisperMic] model loaded")

    def _run(self):
        import sounddevice as sd
        import numpy as np

        silence_frames = int(self._silence_ms / 1000 * self.SAMPLE_RATE / self.CHUNK_FRAMES)
        buffer: list[bytes] = []
        silent_chunks = 0
        speaking = False

        def callback(indata, frames, time_info, status):
            nonlocal silent_chunks, speaking
            pcm = (indata[:, 0] * 32767).astype("int16").tobytes()
            rms = float(np.sqrt(np.mean(indata ** 2)))
            is_silent = rms < self.SILENCE_THRESHOLD
            buffer.append(pcm)
            if not is_silent:
                speaking = True
                silent_chunks = 0
            elif speaking:
                silent_chunks += 1

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="float32",
                blocksize=self.CHUNK_FRAMES,
                callback=callback,
            ):
                if _debug():
                    print("[WhisperMic] microphone open, listening...")
                while not self._stop_event.is_set():
                    time.sleep(0.1)
                    if speaking and silent_chunks >= silence_frames:
                        # End of utterance detected
                        pcm_data = b"".join(buffer)
                        buffer.clear()
                        speaking = False
                        silent_chunks = 0
                        duration = len(pcm_data) / (self.SAMPLE_RATE * 2)
                        if duration < self.MIN_SPEECH_SECONDS:
                            if _debug():
                                print(f"[WhisperMic] clip too short ({duration:.2f}s), skipped")
                            continue
                        self._transcribe_and_append(pcm_data)
        except Exception as e:
            print(f"[WhisperMic] audio stream error: {e}")
        finally:
            self._running = False

    def _transcribe_and_append(self, pcm_bytes: bytes):
        try:
            wav_bytes = self._pcm_to_wav(pcm_bytes)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp = f.name
            try:
                segments, info = self._model.transcribe(
                    tmp,
                    language=self._language,
                    beam_size=5,
                    vad_filter=True,
                )
                text = "".join(s.text for s in segments).strip()
                if _debug():
                    print(f"[WhisperMic] transcribed lang={info.language} text={text!r}")
                if text:
                    with self._transcript_path.open("a", encoding="utf-8") as fh:
                        fh.write(text + "\n")
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception as e:
            if _debug():
                print(f"[WhisperMic] transcribe error: {e}")

    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()


def preload_whisper_model(model: str = "base", language: str = "zh"):
    """Load WhisperModel before QApplication is created.
    Must be called in the main thread before Qt starts to avoid OpenMP/Qt conflict."""
    from faster_whisper import WhisperModel
    device = "cpu"
    compute = "int8"
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
            compute = "float16"
    except ImportError:
        pass
    print(f"[WhisperMic] pre-loading model={model} device={device} (before Qt starts)")
    loaded = WhisperModel(model, device=device, compute_type=compute, cpu_threads=1, local_files_only=True)
    print("[WhisperMic] pre-load complete")
    return loaded


# Module-level cache: {(model, language): WhisperModel}
_preloaded: dict[tuple[str, str], object] = {}


def get_or_preload(model: str = "base", language: str = "zh"):
    key = (model, language)
    if key not in _preloaded:
        _preloaded[key] = preload_whisper_model(model=model, language=language)
    return _preloaded[key]
