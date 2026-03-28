from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QColor
from PyQt6.QtCore import pyqtSignal, QObject


def _make_icon(color: str, size: int = 32) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(color))
    return QIcon(pix)


class TrayIcon(QObject):
    """System tray icon with 3-state color and right-click menu.

    Signals:
        toggle_requested — user clicked Start/Pause
        open_window_requested — user clicked Open Window
        quit_requested — user clicked Quit
    """

    toggle_requested = pyqtSignal()
    open_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    STATE_PAUSED = "paused"
    STATE_RUNNING = "running"
    STATE_BUSY = "busy"

    _STATE_COLORS = {
        STATE_PAUSED: "#9ca3af",
        STATE_RUNNING: "#22c55e",
        STATE_BUSY: "#f59e0b",
    }

    def __init__(self, icon_path: str, parent=None):
        super().__init__(parent)
        self._state = self.STATE_PAUSED

        self._tray = QSystemTrayIcon()
        self._tray.setIcon(QIcon(icon_path))
        self._tray.setToolTip("LOL Coach")
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._toggle_action = self._menu.addAction("开始分析")
        self._toggle_action.triggered.connect(self.toggle_requested)
        self._menu.addSeparator()
        open_action = self._menu.addAction("打开主窗口")
        open_action.triggered.connect(self.open_window_requested)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("退出")
        quit_action.triggered.connect(self.quit_requested)

        self._tray.setContextMenu(self._menu)

    def show(self):
        self._tray.show()

    def set_state(self, state: str):
        self._state = state
        color = self._STATE_COLORS.get(state, "#9ca3af")
        self._tray.setIcon(_make_icon(color))
        if state == self.STATE_PAUSED:
            self._toggle_action.setText("开始分析")
            self._tray.setToolTip("LOL Coach — 已暂停")
        elif state == self.STATE_RUNNING:
            self._toggle_action.setText("暂停分析")
            self._tray.setToolTip("LOL Coach — 运行中")
        elif state == self.STATE_BUSY:
            self._toggle_action.setText("暂停分析")
            self._tray.setToolTip("LOL Coach — AI 分析中...")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_window_requested.emit()
