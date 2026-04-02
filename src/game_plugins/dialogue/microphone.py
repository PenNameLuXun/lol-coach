from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
