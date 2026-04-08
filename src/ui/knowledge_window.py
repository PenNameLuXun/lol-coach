"""Web Knowledge window — embeds game-related websites via QWebEngineView.

Supports two display modes:
- "embed" (default): loads real websites (op.gg, u.gg, etc.) in QWebEngineView tabs
- "text": legacy mode using QTextBrowser with scraped/parsed content
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ui.web_routes import EmbedRoute

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings

    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

from src.web_knowledge import KnowledgeBundle, knowledge_item_tab_label, render_knowledge_item

logger = logging.getLogger("lol_coach.knowledge_window")


# ── Dark CSS injected into every loaded page ────────────────────────────────

_DARK_INJECT_CSS = """
(function() {
    var style = document.createElement('style');
    style.textContent = `
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #12161f; }
        ::-webkit-scrollbar-thumb { background: #2d3644; border-radius: 4px; }
    `;
    document.head.appendChild(style);
})();
"""


class KnowledgeWindow(QWidget):
    def __init__(self, width: int = 560, height: int = 900, parent=None):
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._dismissed = False
        self._bundle: KnowledgeBundle | None = None
        self._content_widget: QWidget | None = None
        self._current_routes: list[EmbedRoute] = []
        self._webviews: list[QWebEngineView] = [] if _HAS_WEBENGINE else []
        self._profile: QWebEngineProfile | None = None

        self.setWindowTitle("Web Knowledge")
        self.resize(width, height)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.92)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        self._panel = QWidget()
        self._panel.setObjectName("knowledgePanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(16, 14, 16, 16)
        panel_layout.setSpacing(10)

        # ── Title bar ────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._title_label = QLabel("Web Knowledge")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet("color: #f6f7fb;")
        toolbar.addWidget(self._title_label, 1)

        self._topmost_button = QPushButton("置顶")
        self._topmost_button.setCheckable(True)
        self._topmost_button.setChecked(True)
        self._topmost_button.clicked.connect(self._toggle_topmost)
        toolbar.addWidget(self._topmost_button)

        toolbar.addWidget(QLabel("透明"))

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(55, 100)
        self._opacity_slider.setValue(92)
        self._opacity_slider.setFixedWidth(92)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self._opacity_slider)

        self._close_button = QPushButton("×")
        self._close_button.setFixedWidth(28)
        self._close_button.clicked.connect(self.dismiss)
        toolbar.addWidget(self._close_button)

        panel_layout.addLayout(toolbar)

        # ── Navigation bar (for embed mode) ──────────────────────────────
        self._nav_bar = QHBoxLayout()
        self._nav_bar.setSpacing(6)

        self._back_button = QPushButton("◀")
        self._back_button.setFixedWidth(32)
        self._back_button.setToolTip("后退")
        self._back_button.clicked.connect(self._on_back)
        self._nav_bar.addWidget(self._back_button)

        self._forward_button = QPushButton("▶")
        self._forward_button.setFixedWidth(32)
        self._forward_button.setToolTip("前进")
        self._forward_button.clicked.connect(self._on_forward)
        self._nav_bar.addWidget(self._forward_button)

        self._refresh_button = QPushButton("↻")
        self._refresh_button.setFixedWidth(32)
        self._refresh_button.setToolTip("刷新")
        self._refresh_button.clicked.connect(self._on_refresh)
        self._nav_bar.addWidget(self._refresh_button)

        self._url_label = QLabel("")
        self._url_label.setStyleSheet("color: #7f8795; font-size: 11px;")
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._nav_bar.addWidget(self._url_label, 1)

        self._open_external_button = QPushButton("↗")
        self._open_external_button.setFixedWidth(32)
        self._open_external_button.setToolTip("在浏览器中打开")
        self._open_external_button.clicked.connect(self._on_open_external)
        self._nav_bar.addWidget(self._open_external_button)

        self._nav_widget = QWidget()
        self._nav_widget.setLayout(self._nav_bar)
        panel_layout.addWidget(self._nav_widget)

        # ── Summary / info label ─────────────────────────────────────────
        self._summary_label = QLabel("暂无资料。")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("color: #b8bfcc; font-size: 12px;")
        panel_layout.addWidget(self._summary_label)

        self._updated_label = QLabel("")
        self._updated_label.setStyleSheet("color: #7f8795; font-size: 11px;")
        panel_layout.addWidget(self._updated_label)

        # ── Content host ─────────────────────────────────────────────────
        self._content_host = QFrame()
        self._content_host.setObjectName("knowledgeContentHost")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().setExpanding(False)
        self._tabs.setStyleSheet(_TAB_STYLESHEET)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._browser.setStyleSheet(_BROWSER_STYLESHEET)
        self._tabs.addTab(self._browser, "资料")
        self._content_layout.addWidget(self._tabs)
        panel_layout.addWidget(self._content_host, 1)

        root.addWidget(self._panel)

        self.setStyleSheet(_WINDOW_STYLESHEET)
        self._nav_widget.hide()
        self.update_bundle(None)

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def is_dismissed(self) -> bool:
        return self._dismissed

    def dismiss(self) -> None:
        self._dismissed = True
        self.hide()

    def revive(self) -> None:
        self._dismissed = False
        self.show()
        self.raise_()
        self.activateWindow()

    def load_routes(self, routes: list[EmbedRoute], *, title: str = "", summary: str = "") -> None:
        """Load embedded website routes (Option C mode)."""
        if not _HAS_WEBENGINE:
            logger.warning("PyQt6-WebEngine not installed, falling back to text mode")
            return
        if routes == self._current_routes:
            return

        self._current_routes = list(routes)
        self._webviews.clear()

        self._title_label.setText(title or "Web Knowledge")
        self._summary_label.setText(summary or "")
        self._updated_label.setText("")
        self._nav_widget.show()

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.currentChanged.connect(self._on_tab_changed)
        tabs.tabBar().setExpanding(False)
        tabs.setStyleSheet(_TAB_STYLESHEET)

        if self._profile is None:
            self._profile = QWebEngineProfile("lol-coach-knowledge", self)
            self._profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9,en;q=0.7")
            self._profile.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )

        for route in routes:
            page = QWebEnginePage(self._profile, self)
            view = QWebEngineView(self)
            view.setPage(page)

            settings = view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

            view.load(QUrl(route.url))
            view.loadFinished.connect(lambda ok, v=view: self._on_page_loaded(v, ok))
            tabs.addTab(view, route.label)
            self._webviews.append(view)

        self._tabs = tabs
        self.set_content_widget(tabs)

        if routes:
            self._url_label.setText(routes[0].url)

    def update_bundle(self, bundle: KnowledgeBundle | None) -> None:
        """Legacy text mode — display parsed web knowledge."""
        self._bundle = bundle
        self._current_routes = []
        self._webviews.clear()
        self._nav_widget.hide()

        self.set_content_widget(self._tabs)
        self._tabs.blockSignals(True)
        self._tabs.clear()
        self._tabs.blockSignals(False)

        if bundle is None or not bundle.items:
            self._title_label.setText("Web Knowledge")
            self._summary_label.setText("暂无资料。")
            self._updated_label.setText("")
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(render_knowledge_item(None, 0))
            self._tabs.addTab(browser, "资料")
            return

        self._title_label.setText(f"{bundle.display_name} Web Knowledge")
        self._summary_label.setText(bundle.summary or "暂无摘要。")
        self._updated_label.setText(f"更新于 {bundle.generated_at.strftime('%H:%M:%S')}")

        for index, item in enumerate(bundle.items):
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setFrameShape(QTextBrowser.Shape.NoFrame)
            browser.setStyleSheet(_BROWSER_STYLESHEET)
            browser.setHtml(render_knowledge_item(bundle, index))
            self._tabs.addTab(browser, knowledge_item_tab_label(item))

        self._tabs.setCurrentIndex(0)

    def set_header(self, *, title: str, summary: str = "", updated_text: str = "") -> None:
        self._title_label.setText(title or "Web Knowledge")
        self._summary_label.setText(summary or "暂无资料。")
        self._updated_label.setText(updated_text)

    def set_content_widget(self, widget: QWidget) -> None:
        if self._content_widget is widget:
            return
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)
        self._content_widget = widget
        self._content_layout.addWidget(widget)

    # ── Navigation handlers ──────────────────────────────────────────────

    def _current_webview(self) -> QWebEngineView | None:
        if not self._webviews:
            return None
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._webviews):
            return self._webviews[idx]
        return None

    def _on_back(self) -> None:
        view = self._current_webview()
        if view:
            view.back()

    def _on_forward(self) -> None:
        view = self._current_webview()
        if view:
            view.forward()

    def _on_refresh(self) -> None:
        view = self._current_webview()
        if view:
            view.reload()

    def _on_open_external(self) -> None:
        view = self._current_webview()
        if view:
            import webbrowser
            webbrowser.open(view.url().toString())

    def _on_tab_changed(self, index: int) -> None:
        if self._webviews and 0 <= index < len(self._webviews):
            url = self._webviews[index].url().toString()
            self._url_label.setText(url if url != "about:blank" else "")
        elif self._current_routes and 0 <= index < len(self._current_routes):
            self._url_label.setText(self._current_routes[index].url)

    def _on_page_loaded(self, view: QWebEngineView, ok: bool) -> None:
        if ok:
            view.page().runJavaScript(_DARK_INJECT_CSS)
            if view == self._current_webview():
                self._url_label.setText(view.url().toString())

    # ── Window drag ──────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _toggle_topmost(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def _on_opacity_changed(self, value: int) -> None:
        self.setWindowOpacity(max(0.3, min(1.0, value / 100.0)))

    def _render_current_tab(self, _index: int) -> None:
        return


# ── Stylesheets ──────────────────────────────────────────────────────────────

_TAB_STYLESHEET = """
QTabWidget::pane {
    border: 1px solid #252c38;
    border-radius: 14px;
    background: #12161f;
    top: -1px;
}
QTabBar::tab {
    background: #171d27;
    color: #cfd6e4;
    padding: 8px 14px;
    margin-right: 6px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border: 1px solid #2c3646;
}
QTabBar::tab:selected {
    background: #24364f;
    color: #f6f7fb;
    border-color: #4d78b8;
}
"""

_BROWSER_STYLESHEET = """
QTextBrowser {
    background: #12161f;
    border: none;
    padding: 8px;
    color: #e8ebf1;
    selection-background-color: #274b8a;
}
QScrollBar:vertical {
    background: #12161f;
    width: 10px;
    margin: 4px 0 4px 0;
}
QScrollBar::handle:vertical {
    background: #2d3644;
    min-height: 28px;
    border-radius: 5px;
}
"""

_WINDOW_STYLESHEET = """
QWidget#knowledgePanel {
    background: rgba(11, 15, 22, 236);
    border: 1px solid rgba(70, 82, 102, 190);
    border-radius: 18px;
}
QPushButton {
    background: #1b2330;
    color: #dbe4f4;
    border: 1px solid #334055;
    border-radius: 10px;
    padding: 5px 10px;
}
QPushButton:hover {
    background: #243043;
}
QPushButton:checked {
    background: #31558f;
    border-color: #5785d8;
}
QLabel {
    color: #dbe4f4;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #1f2734;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -4px 0;
    background: #7fa7ff;
    border-radius: 7px;
}
"""
