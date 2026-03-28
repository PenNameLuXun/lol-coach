from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSlot, Qt
from src.config import Config
from src.history import History
from src.ui.tabs.config_tab import ConfigTab
from src.ui.tabs.log_tab import LogTab
from src.ui.tabs.history_tab import HistoryTab


class MainWindow(QMainWindow):
    """Main application window with 4 tabs. Hidden by default."""

    def __init__(self, config: Config, history: History, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LOL Coach")
        self.resize(700, 500)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self.config_tab = ConfigTab(config)
        self.log_tab = LogTab()
        self.history_tab = HistoryTab(history)

        about_widget = self._build_about()
        tabs.addTab(self.config_tab, "配置")
        tabs.addTab(self.log_tab, "实时日志")
        tabs.addTab(self.history_tab, "对局历史")
        tabs.addTab(about_widget, "关于")

    def _build_about(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel("LOL Coach v0.1.0"))
        layout.addWidget(QLabel("快捷键：见配置页"))
        layout.addWidget(QLabel("截图 → AI分析 → 语音建议"))
        return widget

    @pyqtSlot(str)
    def on_advice(self, text: str):
        """Connected to AI thread signal; update log tab."""
        self.log_tab.append_advice(text)
        self.history_tab.refresh()

    def closeEvent(self, event):
        """Hide to tray instead of closing."""
        event.ignore()
        self.hide()
