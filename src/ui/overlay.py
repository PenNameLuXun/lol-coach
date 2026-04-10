from __future__ import annotations

from collections import deque
from datetime import datetime

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


_MAX_EVENT_ENTRIES = 120
_MAX_LOG_ENTRIES = 240

_KIND_STYLES = {
    "qa_input": {"bg": (61, 121, 255), "border": "#5a8dff", "title": "#d8e6ff", "text": "#eef4ff", "small": False},
    "qa_output": {"bg": (51, 168, 120), "border": "#49b67e", "title": "#d8ffec", "text": "#f1fff7", "small": False},
    "qa_ack": {"bg": (90, 100, 118), "border": "#65748a", "title": "#d8dfeb", "text": "#ecf1f8", "small": True},
    "game_ai": {"bg": (252, 164, 70), "border": "#f0a34b", "title": "#ffe8c7", "text": "#fff7ea", "small": False},
    "rule": {"bg": (255, 96, 96), "border": "#df6868", "title": "#ffdede", "text": "#fff1f1", "small": False},
    "hybrid_rule": {"bg": (255, 96, 96), "border": "#df6868", "title": "#ffdede", "text": "#fff1f1", "small": False},
}

_KIND_LABELS = {
    "qa_input": "QA 输入",
    "qa_output": "QA 回答",
    "qa_ack": "唤醒",
    "game_ai": "对局建议",
    "rule": "规则建议",
    "hybrid_rule": "规则建议",
}

_RIGHT_ALIGNED_KINDS = {"qa_input"}


class OverlayWindow(QWidget):
    """Transparent floating dialogue/log panel with separate subwindows."""

    def __init__(self, fade_after: int = 8):
        super().__init__()
        self._fade_after = fade_after
        self._drag_pos: QPoint | None = None
        self._pos_x = 100
        self._pos_y = 100
        self._event_entries: deque[dict[str, object]] = deque(maxlen=_MAX_EVENT_ENTRIES)
        self._log_entries: deque[dict[str, object]] = deque(maxlen=_MAX_LOG_ENTRIES)
        self._collapsed = False
        self._content_alpha = 0.9
        self._expanded_size = (560, 520)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumSize(320, 72)
        self.resize(*self._expanded_size)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("overlayToolbar")
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        self._title = QLabel("LOL Coach Overlay")
        self._title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        toolbar_layout.addWidget(self._title)

        self._hint = QLabel("拖拽移动  Ctrl+滚轮调文字透明  点击折叠")
        self._hint.setStyleSheet("font-size:11px;")
        toolbar_layout.addWidget(self._hint, 1)

        self._collapse_btn = QPushButton("收起")
        self._collapse_btn.clicked.connect(self.toggle_collapsed)
        toolbar_layout.addWidget(self._collapse_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self.clear)
        toolbar_layout.addWidget(self._clear_btn)

        root.addWidget(self._toolbar)

        self._content_frame = QFrame(self)
        self._content_frame.setObjectName("overlayContent")
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical, self._content_frame)
        splitter.setChildrenCollapsible(False)

        self._event_panel = self._build_panel("关键信息")
        self._event_browser = self._event_panel.findChild(QTextBrowser)
        splitter.addWidget(self._event_panel)

        self._log_panel = self._build_panel("关键日志")
        self._log_browser = self._log_panel.findChild(QTextBrowser)
        splitter.addWidget(self._log_panel)
        splitter.setSizes([320, 160])

        content_layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        footer.addWidget(QSizeGrip(self._content_frame), 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        content_layout.addLayout(footer)

        root.addWidget(self._content_frame, 1)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self.hide)

        self._render_events()
        self._render_logs()
        self._apply_styles()

    def _build_panel(self, title: str) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("overlaySubPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setObjectName("overlaySectionTitle")
        label.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        layout.addWidget(label)

        browser = QTextBrowser(panel)
        browser.setOpenExternalLinks(False)
        browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        browser.setObjectName("overlayBrowser")
        layout.addWidget(browser, 1)
        return panel

    def append_event(self, payload: object):
        if isinstance(payload, str):
            event = {"kind": "log", "text": payload}
        elif isinstance(payload, dict):
            event = dict(payload)
        else:
            event = {"kind": "log", "text": str(payload)}

        kind = str(event.get("kind", "log"))
        text = str(event.get("text", "")).strip()
        if not text:
            return

        item = {
            "kind": kind,
            "text": text,
            "at": str(event.get("at") or datetime.now().strftime("%H:%M:%S")),
            "count": 1,
        }
        if kind == "log":
            self._log_entries.append(item)
            self._render_logs()
            self._scroll_to_bottom(self._log_browser)
        else:
            if self._event_entries:
                last = self._event_entries[-1]
                if str(last.get("kind")) == kind and str(last.get("text")) == text:
                    last["count"] = int(last.get("count", 1)) + 1
                    last["at"] = item["at"]
                else:
                    self._event_entries.append(item)
            else:
                self._event_entries.append(item)
            self._render_events()
            self._scroll_to_bottom(self._event_browser)

        if not self.isVisible():
            self.show()
        self.raise_()
        if self._fade_after > 0 and not self._collapsed:
            self._fade_timer.start(self._fade_after * 1000)

    def show_advice(self, text: str):
        self.append_event({"kind": "game_ai", "text": text})

    def clear(self):
        self._event_entries.clear()
        self._log_entries.clear()
        self._render_events()
        self._render_logs()

    def toggle_collapsed(self):
        if self._collapsed:
            self._collapsed = False
            self._collapse_btn.setText("收起")
            self._content_frame.show()
            self.resize(*self._expanded_size)
        else:
            self._expanded_size = (self.width(), self.height())
            self._collapsed = True
            self._collapse_btn.setText("展开")
            self._content_frame.hide()
            self.resize(max(320, self.width()), 64)

    def move_to(self, x: int, y: int):
        self._pos_x = x
        self._pos_y = y
        self.move(x, y)

    def _render_events(self):
        if not self._event_entries:
            self._event_browser.setHtml(self._empty_html("等待 QA / 建议 / 规则消息…"))
            return
        parts = [self._html_start()]
        for entry in self._event_entries:
            kind = str(entry["kind"])
            style = _KIND_STYLES.get(kind, _KIND_STYLES["game_ai"])
            label = _KIND_LABELS.get(kind, kind)
            font_size = "12px" if style["small"] else "15px"
            title_size = "10px" if style["small"] else "11px"
            bg = self._rgba(style["bg"], 0.26 if style["small"] else 0.30)
            align = "right" if kind in _RIGHT_ALIGNED_KINDS else "left"
            if kind == "qa_output":
                bubble_radius = "16px 16px 16px 4px"
            elif align == "right":
                bubble_radius = "16px 16px 4px 16px"
            else:
                bubble_radius = "16px 16px 16px 8px"
            count = int(entry.get("count", 1))
            count_badge = (
                f"<span style='margin-left:6px;padding:1px 6px;border-radius:999px;"
                f"background:{self._rgba(style['bg'], 0.42)};color:{style['title']};'>x{count}</span>"
                if count > 1
                else ""
            )
            parts.append(
                f"<div style='margin:0 0 8px 0;text-align:{align};'>"
                "<div style='display:inline-block;max-width:88%;padding:8px 10px;"
                f"border-radius:{bubble_radius};"
                f"background:{bg};border:1px solid {style['border']};text-align:left;'>"
                f"<div style='font-size:{title_size};color:{style['title']};margin-bottom:4px;'>"
                f"{entry['at']} · {label}{count_badge}</div>"
                f"<div style='font-size:{font_size};color:{style['text']};white-space:pre-wrap;'>"
                f"{_escape_html(str(entry['text']))}</div></div></div>"
            )
        parts.append("</body></html>")
        self._event_browser.setHtml("".join(parts))

    def _render_logs(self):
        if not self._log_entries:
            self._log_browser.setHtml(self._empty_html("等待关键日志…"))
            return
        parts = [self._html_start()]
        for entry in self._log_entries:
            parts.append(
                "<div style='margin:0 0 6px 0;padding:5px 8px;border-radius:8px;"
                f"background:{self._rgba((82, 92, 110), 0.18)};border:1px solid rgba(90,102,122,140);'>"
                "<div style='font-size:10px;color:#8f99a8;margin-bottom:2px;'>"
                f"{entry['at']} · 日志</div>"
                "<div style='font-size:12px;color:#a9b2c1;white-space:pre-wrap;'>"
                f"{_escape_html(str(entry['text']))}</div></div>"
            )
        parts.append("</body></html>")
        self._log_browser.setHtml("".join(parts))

    def _html_start(self) -> str:
        return (
            "<html><body style='font-family:Microsoft YaHei,Segoe UI,sans-serif;"
            "background:transparent;color:#eef2f8;margin:0;'>"
        )

    def _empty_html(self, text: str) -> str:
        return (
            self._html_start()
            + f"<div style='padding:6px;color:#8f99a8;font-size:12px;'>{_escape_html(text)}</div></body></html>"
        )

    def _rgba(self, rgb: tuple[int, int, int], alpha: float) -> str:
        value = max(0.10, min(1.0, alpha * self._content_alpha))
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {value:.3f})"

    def _apply_styles(self):
        toolbar_bg = self._rgba((10, 15, 24), 0.72)
        panel_bg = self._rgba((10, 14, 22), 0.48)
        browser_bg = self._rgba((7, 10, 16), 0.18)
        self._toolbar.setStyleSheet(
            f"QFrame#overlayToolbar {{ background:{toolbar_bg}; border:1px solid rgba(82,96,120,160); border-radius:14px; }}"
            "QLabel { color:#eef3fb; }"
            "QPushButton { background:rgba(28,38,54,170); color:#dbe5f4; border:1px solid #3a4b63; border-radius:8px; padding:4px 10px; }"
            "QPushButton:hover { background:rgba(43,58,80,190); }"
        )
        self._content_frame.setStyleSheet("background: transparent; border: none;")
        for panel in (self._event_panel, self._log_panel):
            panel.setStyleSheet(
                f"QFrame#overlaySubPanel {{ background:{panel_bg}; border:1px solid rgba(72,86,108,150); border-radius:14px; }}"
                "QLabel#overlaySectionTitle { color:#dbe4f4; }"
                f"QTextBrowser#overlayBrowser {{ background:{browser_bg}; border:1px solid rgba(58,68,84,110); border-radius:10px; color:#eef2f8; padding:6px; selection-background-color:#355b9e; }}"
                "QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 0 4px 0; }"
                "QScrollBar::handle:vertical { background: rgba(96,108,128,180); min-height: 30px; border-radius: 5px; }"
            )

    def _scroll_to_bottom(self, browser: QTextBrowser):
        browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        pos = self.pos()
        self._pos_x = pos.x()
        self._pos_y = pos.y()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 0.08 if event.angleDelta().y() > 0 else -0.08
            self._content_alpha = max(0.28, min(1.0, self._content_alpha + delta))
            self._apply_styles()
            self._render_events()
            self._render_logs()
            event.accept()
            return
        super().wheelEvent(event)


def _escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
