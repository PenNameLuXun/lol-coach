from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from src.audio.mic_transcription_service import QtMicTranscriptionService


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "windows_stt_listener.ps1"
WHISPER_WORKER = ROOT / "scripts" / "whisper_stt_worker.py"


def _debug_stt_enabled() -> bool:
    return os.environ.get("LOL_COACH_DEBUG_STT", "").strip().lower() in {"1", "true", "yes", "on"}


class WindowsMicrophoneListener:
    def __init__(self, plugin_id: str):
        self._plugin_id = plugin_id
        self._process: subprocess.Popen | None = None
        self._last_transcript_path: Path | None = None
        self._last_culture = "zh-CN"

    def ensure_running(self, transcript_path: Path, culture: str = "zh-CN") -> bool:
        if sys.platform != "win32":
            return False
        self._last_transcript_path = transcript_path
        self._last_culture = culture
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

    def resume(self) -> bool:
        if self._last_transcript_path is None:
            return False
        return self.ensure_running(self._last_transcript_path, culture=self._last_culture)


class WhisperSubprocessListener:
    """Runs whisper_stt_worker.py as a subprocess — avoids Qt/OpenMP conflict."""

    def __init__(self, plugin_id: str):
        self._plugin_id = plugin_id
        self._process: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._last_transcript_path: Path | None = None
        self._last_culture = "zh-CN"
        self._last_silence_ms = 1000
        self._last_model = "base"
        self._last_backend = "whisper"
        self._pause_flag_path: Path | None = None
        self._partial_transcript_path: Path | None = None

    def ensure_running(
        self,
        transcript_path: Path,
        culture: str = "zh-CN",
        *,
        silence_ms: int = 1000,
        model: str = "base",
        backend: str = "whisper",
    ) -> bool:
        self._last_transcript_path = transcript_path
        self._last_culture = culture
        self._last_silence_ms = silence_ms
        self._last_model = model
        self._last_backend = backend
        self._pause_flag_path = transcript_path.with_suffix(transcript_path.suffix + ".paused")
        self._partial_transcript_path = transcript_path.with_suffix(transcript_path.suffix + ".partial")
        if self._process is not None and self._process.poll() is None:
            return True
        lang = culture.split("-")[0]
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if _debug_stt_enabled():
            print(
                f"[LocalSTT] starting subprocess "
                f"backend={backend} lang={lang} model={model} silence_ms={silence_ms} "
                f"transcript={transcript_path}"
            )
        env = os.environ.copy()
        self._process = subprocess.Popen(
            [
                sys.executable,
                str(WHISPER_WORKER),
                "--transcript", str(transcript_path),
                "--language", lang,
                "--backend", backend,
                "--model", model,
                "--silence-ms", str(silence_ms),
                "--pause-flag", str(self._pause_flag_path),
                "--partial-transcript", str(self._partial_transcript_path),
            ],
            cwd=str(ROOT),
            creationflags=creationflags,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
        )
        if _debug_stt_enabled():
            print(f"[LocalSTT] pid={self._process.pid}")
        self._start_log_pumps()
        return True

    def stop(self) -> None:
        self._clear_pause_flag()
        self._clear_partial_transcript()
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except Exception:
                pass
        self._process = None
        self._stderr_thread = None
        self._stdout_thread = None

    def resume(self) -> bool:
        self._clear_pause_flag()
        if self._last_transcript_path is None:
            return False
        return self.ensure_running(
            self._last_transcript_path,
            culture=self._last_culture,
            silence_ms=self._last_silence_ms,
            model=self._last_model,
            backend=self._last_backend,
        )

    def pause(self) -> None:
        if self._pause_flag_path is None:
            return
        try:
            self._pause_flag_path.write_text("paused\n", encoding="utf-8")
            if _debug_stt_enabled():
                print(f"[LocalSTT] pause flag on: {self._pause_flag_path.name}")
        except Exception as exc:
            if _debug_stt_enabled():
                print(f"[LocalSTT] failed to set pause flag: {exc}")

    def _clear_pause_flag(self) -> None:
        if self._pause_flag_path is None:
            return
        try:
            if self._pause_flag_path.exists():
                self._pause_flag_path.unlink()
                if _debug_stt_enabled():
                    print(f"[LocalSTT] pause flag off: {self._pause_flag_path.name}")
        except Exception as exc:
            if _debug_stt_enabled():
                print(f"[LocalSTT] failed to clear pause flag: {exc}")

    def _clear_partial_transcript(self) -> None:
        if self._partial_transcript_path is None:
            return
        try:
            if self._partial_transcript_path.exists():
                self._partial_transcript_path.unlink()
        except Exception:
            pass

    def _start_log_pumps(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._pump_stream,
                args=(process.stderr, "[LocalSTT][stderr]"),
                daemon=True,
            )
            self._stderr_thread.start()
        if process.stdout is not None:
            self._stdout_thread = threading.Thread(
                target=self._pump_stream,
                args=(process.stdout, "[LocalSTT][stdout]"),
                daemon=True,
            )
            self._stdout_thread.start()

    def _pump_stream(self, stream, prefix: str) -> None:
        try:
            for raw_line in iter(stream.readline, ""):
                line = raw_line.strip()
                if not line:
                    continue
                if _debug_stt_enabled():
                    print(f"{prefix} {line}")
        except Exception as exc:
            if _debug_stt_enabled():
                print(f"{prefix} <pump error: {exc}>")


class QtMicrophoneListener:
    def __init__(self, plugin_id: str):
        self._plugin_id = plugin_id
        self._service = None
        self._last_transcript_path: Path | None = None
        self._last_culture = "zh-CN"
        self._last_silence_ms = 1000
        self._last_stt_backend = "system"

    def ensure_running(
        self,
        transcript_path: Path,
        culture: str = "zh-CN",
        *,
        silence_ms: int = 1000,
        stt_backend: str = "system",
    ) -> bool:
        self._last_transcript_path = transcript_path
        self._last_culture = culture
        self._last_silence_ms = silence_ms
        self._last_stt_backend = stt_backend
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

    def resume(self) -> bool:
        if self._last_transcript_path is None:
            return False
        return self.ensure_running(
            self._last_transcript_path,
            culture=self._last_culture,
            silence_ms=self._last_silence_ms,
            stt_backend=self._last_stt_backend,
        )


class MicrophoneListener:
    def __init__(self, plugin_id: str):
        self._windows = WindowsMicrophoneListener(plugin_id=plugin_id)
        self._qt = QtMicrophoneListener(plugin_id=plugin_id)
        self._whisper = WhisperSubprocessListener(plugin_id=plugin_id)
        self._active_listener: str | None = None

    def ensure_running(
        self,
        transcript_path: Path,
        culture: str = "zh-CN",
        *,
        backend: str = "powershell",
        silence_ms: int = 1000,
        stt_backend: str = "system",
        whisper_model: str = "base",
        funasr_model: str = "paraformer-zh",
    ) -> bool:
        backend_name = str(backend).strip().lower()
        if stt_backend in {"whisper", "funasr"}:
            self._active_listener = "whisper"
            return self._whisper.ensure_running(
                transcript_path,
                culture=culture,
                silence_ms=silence_ms,
                model=funasr_model if stt_backend == "funasr" else whisper_model,
                backend=stt_backend,
            )
        if backend_name == "qt":
            self._active_listener = "qt"
            return self._qt.ensure_running(
                transcript_path,
                culture=culture,
                silence_ms=silence_ms,
                stt_backend=stt_backend,
            )
        self._active_listener = "windows"
        return self._windows.ensure_running(transcript_path, culture=culture)

    def stop(self) -> None:
        self._windows.stop()
        self._qt.stop()
        self._whisper.stop()
        self._active_listener = None

    def pause(self) -> None:
        if self._active_listener == "whisper":
            self._whisper.pause()
            return
        elif self._active_listener == "qt":
            self._qt.stop()
        elif self._active_listener == "windows":
            self._windows.stop()

    def resume(self) -> bool:
        if self._active_listener == "whisper":
            return self._whisper.resume()
        if self._active_listener == "qt":
            return self._qt.resume()
        if self._active_listener == "windows":
            return self._windows.resume()
        return False
