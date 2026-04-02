from __future__ import annotations

from typing import Optional

try:
    from PyQt6.QtCore import QObject, pyqtSignal
except Exception:  # pragma: no cover
    QObject = object  # type: ignore[assignment]

    def pyqtSignal(*_args, **_kwargs):  # type: ignore[override]
        return None


class QtMicCapture(QObject):
    audio_chunk = pyqtSignal(bytes)

    def __init__(self, parent: Optional[QObject] = None):
        try:
            super().__init__(parent)  # type: ignore[misc]
        except TypeError:
            super().__init__()  # type: ignore[misc]
        self._running = False

    def is_supported(self) -> bool:
        try:
            from PyQt6 import QtMultimedia  # noqa: F401
        except Exception:
            return False
        return True

    def start(self) -> bool:
        if not self.is_supported():
            return False
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running
