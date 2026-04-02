from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

from src.audio.mic_capture import QtMicCapture
from src.audio.speech_segmenter import SpeechSegmenter
from src.stt.base import SttEngine
from src.stt.system_engine import NullSttEngine

try:
    from PyQt6.QtCore import QProcess
except Exception:  # pragma: no cover - import guard for non-Qt env
    QProcess = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "windows_stt_listener.ps1"


def _debug_stt_enabled() -> bool:
    return os.environ.get("LOL_COACH_DEBUG_STT", "").strip().lower() in {"1", "true", "yes", "on"}


class QtMicTranscriptionService:
    def __init__(
        self,
        *,
        transcript_path: Path,
        culture: str = "zh-CN",
        silence_ms: int = 1000,
        stt_backend: str = "system",
        stt_engine: Optional[SttEngine] = None,
    ):
        self._transcript_path = transcript_path
        self._culture = culture
        self._stt_backend = str(stt_backend).strip().lower()
        self._capture = QtMicCapture()
        self._segmenter = SpeechSegmenter(silence_ms=silence_ms)
        self._stt_engine = stt_engine or NullSttEngine(language=culture)
        self._started = False
        self._process: QProcess | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stdout_stop = threading.Event()
        self._stdout_buffer = ""

    def is_supported(self) -> bool:
        if self._stt_backend == "system":
            return bool(sys.platform == "win32" and QProcess is not None and SCRIPT_PATH.exists())
        return self._capture.is_supported() and self._stt_engine.is_supported()

    def start(self) -> bool:
        if not self.is_supported():
            if _debug_stt_enabled():
                print("[QtMic] unsupported backend or missing runtime")
            return False
        self._transcript_path.parent.mkdir(parents=True, exist_ok=True)
        if self._stt_backend == "system":
            if self._process is None:
                self._process = QProcess()
                self._process.setWorkingDirectory(str(ROOT))
                self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
                self._process.errorOccurred.connect(self._on_process_error)
                self._process.finished.connect(self._on_process_finished)
                self._process.stateChanged.connect(self._on_process_state_changed)
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._started = True
                if _debug_stt_enabled():
                    print("[QtMic] system STT process already running")
                return True
            if not self._transcript_path.exists():
                self._transcript_path.write_text("", encoding="utf-8")
            if _debug_stt_enabled():
                print(
                    "[QtMic] starting system STT "
                    f"culture={self._culture} transcript={self._transcript_path}"
                )
            self._process.start(
                "powershell",
                [
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(SCRIPT_PATH),
                    "-Culture",
                    self._culture,
                    "-OutputMode",
                    "stdout",
                ],
            )
            self._started = self._process.waitForStarted(3000)
            if _debug_stt_enabled():
                print(f"[QtMic] process started={self._started}")
            if self._started:
                self._start_stdout_pump()
            else:
                self._drain_stderr()
            return self._started
        self._started = self._capture.start()
        if _debug_stt_enabled():
            print(f"[QtMic] qt audio capture started={self._started}")
        return self._started

    def stop(self) -> None:
        if _debug_stt_enabled():
            print("[QtMic] stopping transcription service")
        self._stdout_stop.set()
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=1.5)
        self._stdout_thread = None
        if self._process is not None:
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._process.terminate()
                self._process.waitForFinished(1500)
            self._process = None
        self._capture.stop()
        self._segmenter.reset()
        self._started = False

    def is_running(self) -> bool:
        if self._process is not None:
            return self._started and self._process.state() != QProcess.ProcessState.NotRunning
        return self._started and self._capture.is_running()

    def _start_stdout_pump(self) -> None:
        if self._process is None:
            return
        self._stdout_stop.clear()
        self._stdout_buffer = ""
        if _debug_stt_enabled():
            print("[QtMic] stdout pump started")
        self._stdout_thread = threading.Thread(target=self._pump_stdout_loop, daemon=True)
        self._stdout_thread.start()

    def _pump_stdout_loop(self) -> None:
        process = self._process
        if process is None:
            return
        while not self._stdout_stop.is_set():
            if process.state() == QProcess.ProcessState.NotRunning:
                self._drain_stderr()
                break
            if not process.waitForReadyRead(250):
                self._drain_stderr()
                continue
            chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="ignore")
            if not chunk:
                self._drain_stderr()
                continue
            if _debug_stt_enabled():
                print(f"[QtMic] stdout chunk={chunk!r}")
            self._stdout_buffer += chunk
            while "\n" in self._stdout_buffer:
                line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
                self._append_transcript_line(line.strip())
        if self._stdout_buffer.strip():
            self._append_transcript_line(self._stdout_buffer.strip())
            self._stdout_buffer = ""

    def _append_transcript_line(self, text: str) -> None:
        if not text:
            return
        try:
            with self._transcript_path.open("a", encoding="utf-8") as handle:
                handle.write(text + "\n")
            if _debug_stt_enabled():
                print(f"[QtMic] appended transcript text={text!r}")
        except Exception:
            if _debug_stt_enabled():
                print(f"[QtMic] failed to append transcript text={text!r}")
            return

    def _drain_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", errors="ignore")
        if chunk.strip() and _debug_stt_enabled():
            print(f"[QtMic][stderr] {chunk.rstrip()}")

    def _on_process_error(self, error) -> None:
        if _debug_stt_enabled():
            print(f"[QtMic] process error={error}")
        self._drain_stderr()

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        if _debug_stt_enabled():
            print(f"[QtMic] process finished exit_code={exit_code} exit_status={exit_status}")
        self._drain_stderr()

    def _on_process_state_changed(self, state) -> None:
        if _debug_stt_enabled():
            print(f"[QtMic] process state={state}")
