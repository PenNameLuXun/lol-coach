from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QFont, QColor


class OverlayWindow(QWidget):
    """Frameless always-on-top transparent overlay that shows the latest advice.

    Drag to reposition. Fades out after `fade_after` seconds (0 = stay).
    """

    def __init__(self, fade_after: int = 8):
        super().__init__()
        self._fade_after = fade_after
        self._drag_pos: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        self._label.setStyleSheet(
            "color: #00ff88; background: rgba(0,0,0,180); "
            "border-radius: 8px; padding: 8px 12px;"
        )
        self._label.setMaximumWidth(600)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.setContentsMargins(4, 4, 4, 4)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self.hide)

    def show_advice(self, text: str):
        self._label.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        if self._fade_after > 0:
            self._fade_timer.start(self._fade_after * 1000)

    def move_to(self, x: int, y: int):
        self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
