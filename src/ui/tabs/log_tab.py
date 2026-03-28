from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QFont


class LogTab(QWidget):
    """Scrolling real-time log of AI advice with timestamps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 10))
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self._text.clear)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def append_advice(self, text: str):
        """Called from main thread via Qt Signal."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.append(f"<span style='color:#6b7280'>[{ts}]</span> {text}")
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())
