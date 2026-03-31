from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QToolButton, QVBoxLayout, QWidget


class CollapsibleBox(QWidget):
    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(not collapsed)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.clicked.connect(self._on_toggled)

        self._content = QFrame()
        self._content.setVisible(not collapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 0, 0, 0)
        self._content_layout.setSpacing(6)
        self._sync_arrow()

    def setContentWidget(self, widget: QWidget):
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        self._content_layout.addWidget(widget)

    def _on_toggled(self):
        expanded = self._toggle.isChecked()
        self._content.setVisible(expanded)
        self._sync_arrow()

    def _sync_arrow(self):
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._toggle.isChecked() else Qt.ArrowType.RightArrow
        )
