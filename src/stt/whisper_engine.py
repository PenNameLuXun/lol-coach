from __future__ import annotations

import io
import os
import tempfile


class WhisperSttEngine:
    """STT engine backed by faster-whisper (local, no API key needed).

    Install: pip install faster-whisper
    Models:  tiny / base / small / medium / large-v3
             tiny   ~39MB  fastest, lower accuracy
             base   ~74MB  good balance for Chinese
             small  ~244MB better accuracy
             medium ~769MB high accuracy
    """

    def __init__(self, model: str = "base", language: str = "zh"):
        self._model_name = model
        self._language = language
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore
            device = "cpu"
            compute = "int8"
            try:
                import torch  # type: ignore
                if torch.cuda.is_available():
                    device = "cuda"
                    compute = "float16"
            except ImportError:
                pass
            self._model = WhisperModel(self._model_name, device=device, compute_type=compute)
        except ImportError:
            self._model = None

    def is_supported(self) -> bool:
        try:
            import faster_whisper  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, wav_bytes: bytes) -> str | None:
        self._load()
        if self._model is None:
            return None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name
            try:
                segments, _ = self._model.transcribe(
                    tmp_path,
                    language=self._language,
                    beam_size=5,
                    vad_filter=True,
                )
                text = "".join(seg.text for seg in segments).strip()
                return text if text else None
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            print(f"[WhisperSTT] transcribe error: {e}")
            return None
