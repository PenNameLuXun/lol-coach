from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.audio.mic_transcription_service import QtMicTranscriptionService


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "windows_stt_listener.ps1"


class WindowsMicrophoneListener:
    def __init__(self, plugin_id: str):
        self._plugin_id = plugin_id
        self._process: subprocess.Popen | None = None

    def ensure_running(self, transcript_path: Path, culture: str = "zh-CN") -> bool:
        if sys.platform != "win32":
            return False
        if self._process is not None and self._process.poll() is None:
            return True
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        if not SCRIPT_PATH.exists():
            return False
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(SCRIPT_PATH),
                "-TranscriptPath",
                str(transcript_path),
                "-Culture",
                culture,
            ],
            cwd=str(ROOT),
            creationflags=creationflags,
        )
        return True

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
        self._process = None


class QtMicrophoneListener:
    def __init__(self, plugin_id: str):
        self._plugin_id = plugin_id
        self._service: QtMicTranscriptionService | None = None

    def ensure_running(
        self,
        transcript_path: Path,
        culture: str = "zh-CN",
        *,
        silence_ms: int = 1000,
        stt_backend: str = "system",
    ) -> bool:
        if self._service is None:
            self._service = QtMicTranscriptionService(
                transcript_path=transcript_path,
                culture=culture,
                silence_ms=silence_ms,
                stt_backend=stt_backend,
            )
        if self._service.is_running():
            return True
        return self._service.start()

    def stop(self) -> None:
        if self._service is None:
            return
        self._service.stop()


class MicrophoneListener:
    def __init__(self, plugin_id: str):
        self._windows = WindowsMicrophoneListener(plugin_id=plugin_id)
        self._qt = QtMicrophoneListener(plugin_id=plugin_id)

    def ensure_running(
        self,
        transcript_path: Path,
        culture: str = "zh-CN",
        *,
        backend: str = "powershell",
        silence_ms: int = 1000,
        stt_backend: str = "system",
    ) -> bool:
        backend_name = str(backend).strip().lower()
        if backend_name == "qt":
            return self._qt.ensure_running(
                transcript_path,
                culture=culture,
                silence_ms=silence_ms,
                stt_backend=stt_backend,
            )
        return self._windows.ensure_running(transcript_path, culture=culture)

    def stop(self) -> None:
        self._windows.stop()
        self._qt.stop()
