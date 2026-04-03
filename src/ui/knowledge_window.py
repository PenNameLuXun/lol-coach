from PyQt6.QtCore import QPoint, Qt
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

from src.web_knowledge import KnowledgeBundle, knowledge_item_tab_label, render_knowledge_item


class KnowledgeWindow(QWidget):
    def __init__(self, width: int = 560, height: int = 900, parent=None):
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._dismissed = False
        self._bundle: KnowledgeBundle | None = None
        self._content_widget: QWidget | None = None

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

        self._summary_label = QLabel("暂无资料。")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("color: #b8bfcc; font-size: 12px;")
        panel_layout.addWidget(self._summary_label)

        self._updated_label = QLabel("")
        self._updated_label.setStyleSheet("color: #7f8795; font-size: 11px;")
        panel_layout.addWidget(self._updated_label)

        self._content_host = QFrame()
        self._content_host.setObjectName("knowledgeContentHost")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._render_current_tab)
        self._tabs.tabBar().setExpanding(False)
        self._tabs.setStyleSheet(
            """
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
        )

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._browser.setStyleSheet(
            """
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
        )
        self._tabs.addTab(self._browser, "资料")
        self._content_layout.addWidget(self._tabs)
        panel_layout.addWidget(self._content_host, 1)

        root.addWidget(self._panel)

        self.setStyleSheet(
            """
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
        )
        self.update_bundle(None)

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

    def update_bundle(self, bundle: KnowledgeBundle | None) -> None:
        self._bundle = bundle
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
            browser.setStyleSheet(self._browser.styleSheet())
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
        # Each tab already owns its rendered browser content.
        return
