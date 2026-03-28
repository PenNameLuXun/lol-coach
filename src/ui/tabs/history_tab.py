from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QFileDialog, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt
from src.history import History


class HistoryTab(QWidget):
    """Session-grouped history viewer with export and session marking."""

    def __init__(self, history: History, parent=None):
        super().__init__(parent)
        self._history = history
        self._current_session_id: int | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._session_list = QListWidget()
        self._session_list.currentRowChanged.connect(self._on_session_selected)
        left_layout.addWidget(self._session_list)

        session_btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ 开始新场次")
        self._end_btn = QPushButton("⏹ 结束场次")
        self._end_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start_session)
        self._end_btn.clicked.connect(self._end_session)
        session_btn_row.addWidget(self._start_btn)
        session_btn_row.addWidget(self._end_btn)
        left_layout.addLayout(session_btn_row)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        right_layout.addWidget(self._detail)

        export_btn = QPushButton("导出为文本...")
        export_btn.clicked.connect(self._export)
        right_layout.addWidget(export_btn)

        splitter.addWidget(right)
        splitter.setSizes([200, 400])
        layout.addWidget(splitter)

    def refresh(self):
        self._session_list.clear()
        for s in self._history.list_sessions():
            label = f"场次 {s['id']}  {s['started'][:16]}"
            if not s['ended']:
                label += "  [进行中]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s['id'])
            self._session_list.addItem(item)

    def _on_session_selected(self, row: int):
        if row < 0:
            return
        session_id = self._session_list.item(row).data(Qt.ItemDataRole.UserRole)
        rows = self._history.list_advice(session_id=session_id)
        lines = [f"[{r['timestamp'][11:19]}] ({r['trigger']}) {r['text']}" for r in rows]
        self._detail.setPlainText("\n".join(lines))

    def _start_session(self):
        self._current_session_id = self._history.start_session()
        self._start_btn.setEnabled(False)
        self._end_btn.setEnabled(True)
        self.refresh()

    def _end_session(self):
        if self._current_session_id is not None:
            self._history.end_session(self._current_session_id)
            self._current_session_id = None
        self._start_btn.setEnabled(True)
        self._end_btn.setEnabled(False)
        self.refresh()

    def _export(self):
        item = self._session_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个场次")
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        text = self._history.export_session(session_id)
        path, _ = QFileDialog.getSaveFileName(self, "导出场次", f"session_{session_id}.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    def get_current_session_id(self) -> int | None:
        return self._current_session_id
