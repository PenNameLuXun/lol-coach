from __future__ import annotations

import json
from collections import deque
from datetime import datetime

from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QFont, QMouseEvent
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)


_MAX_EVENT_ENTRIES = 120
_MAX_LOG_ENTRIES = 240
_RESIZE_MARGIN = 10

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


class _DragHandleFrame(QFrame):
    def __init__(self, owner: "OverlayWindow"):
        super().__init__(owner)
        self._owner = owner

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner._drag_pos = event.globalPosition().toPoint() - self._owner.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._owner._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self._owner.move(event.globalPosition().toPoint() - self._owner._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._owner._drag_pos = None
        pos = self._owner.pos()
        self._owner._pos_x = pos.x()
        self._owner._pos_y = pos.y()
        super().mouseReleaseEvent(event)


class OverlayWindow(QWidget):
    """Transparent floating dialogue/log panel powered by a small web UI."""

    def __init__(self, fade_after: int = 8):
        super().__init__()
        self._fade_after = fade_after
        self._drag_pos: QPoint | None = None
        self._resize_edges: set[str] = set()
        self._resize_start_global: QPoint | None = None
        self._resize_start_geometry = None
        self._pos_x = 100
        self._pos_y = 100
        self._event_entries: deque[dict[str, object]] = deque(maxlen=_MAX_EVENT_ENTRIES)
        self._log_entries: deque[dict[str, object]] = deque(maxlen=_MAX_LOG_ENTRIES)
        self._collapsed = False
        self._content_alpha = 0.9
        self._hit_test_alpha = 0.04
        self._expanded_size = (560, 520)
        self._web_ready = False
        self.setObjectName("overlayRoot")

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

        self._toolbar = _DragHandleFrame(self)
        self._toolbar.setObjectName("overlayToolbar")
        self._toolbar.setMinimumHeight(48)
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        self._title = QLabel("LOL Coach Overlay")
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        toolbar_layout.addWidget(self._title)

        self._hint = QLabel("拖拽移动  Ctrl+滚轮调文字透明  点击折叠")
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
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
        content_layout.setSpacing(0)

        self._view = QWebEngineView(self._content_frame)
        self._view.setObjectName("overlayWebView")
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self._view.loadFinished.connect(self._on_web_load_finished)
        self._view.setHtml(self._initial_html(), QUrl("about:blank"))
        content_layout.addWidget(self._view, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        footer.addWidget(QSizeGrip(self._content_frame), 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        content_layout.addLayout(footer)

        root.addWidget(self._content_frame, 1)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self.hide)

        self._apply_styles()

    def _initial_html(self) -> str:
        return """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root {
      --content-alpha: 0.9;
      --panel-bg: rgba(8, 12, 18, 0.04);
      --panel-border: rgba(72, 86, 108, 0.58);
      --browser-border: rgba(58, 68, 84, 0.43);
      --section-title: #dbe4f4;
      --empty: #8f99a8;
      --log-title: #8f99a8;
      --log-text: #a9b2c1;
      --log-bg: rgba(82, 92, 110, 0.18);
      --log-border: rgba(90, 102, 122, 0.55);
      color-scheme: dark;
    }
    html, body {
      margin: 0;
      padding: 0;
      background: transparent;
      color: #eef2f8;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      overflow: hidden;
      height: 100%;
    }
    #app {
      height: 100vh;
      display: grid;
      grid-template-rows: minmax(0, 1fr) minmax(150px, 0.65fr);
      gap: 4px;
      padding: 0;
      box-sizing: border-box;
      background: transparent;
    }
    .panel {
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 14px;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .panel-title {
      padding: 5px 9px 3px;
      color: var(--section-title);
      font-size: 12px;
      font-weight: 700;
      flex: 0 0 auto;
    }
    .panel-body {
      margin: 0 8px 8px;
      padding: 2px;
      border: 1px solid var(--browser-border);
      border-radius: 10px;
      background: var(--panel-bg);
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      box-sizing: border-box;
    }
    .events-body {
      padding: 4px 6px 6px;
    }
    .logs-shell {
      margin: 0 8px 8px;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .log-filters {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 0 2px 1px;
      flex: 0 0 auto;
    }
    .filter-chip {
      border: 1px solid rgba(86, 102, 126, 0.7);
      border-radius: 999px;
      padding: 3px 10px;
      background: rgba(20, 28, 40, 0.30);
      color: #b9c3d4;
      font-size: 10px;
      line-height: 1;
      cursor: pointer;
      user-select: none;
      transition: background .18s ease, border-color .18s ease, color .18s ease, transform .18s ease;
    }
    .filter-chip:hover {
      background: rgba(42, 57, 78, 0.48);
      border-color: rgba(112, 131, 160, 0.9);
      transform: translateY(-1px);
    }
    .filter-chip.active {
      background: rgba(61, 121, 255, 0.24);
      border-color: rgba(90, 141, 255, 0.95);
      color: #e8f1ff;
    }
    .logs-body {
      margin: 0;
      flex: 1 1 auto;
      min-height: 0;
    }
    .event-row {
      display: flex;
      margin-bottom: 4px;
      width: 100%;
      animation: bubbleIn .22s ease-out;
    }
    .event-row.right {
      justify-content: flex-end;
    }
    .event-row.left {
      justify-content: flex-start;
    }
    .bubble {
      max-width: 88%;
      display: inline-flex;
      flex-direction: column;
      gap: 2px;
      padding: 4px 8px;
      border-radius: 16px;
      box-sizing: border-box;
      border: 1px solid transparent;
      text-align: left;
      word-break: break-word;
      white-space: pre-wrap;
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.12);
    }
    .bubble-title {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-bottom: 0;
      font-size: 9px;
      line-height: 1.15;
    }
    .count-badge {
      padding: 0 5px;
      border-radius: 999px;
      font-size: 9px;
    }
    .bubble-body {
      font-size: 13px;
      line-height: 1.24;
    }
    .bubble.small .bubble-title {
      font-size: 9px;
    }
    .bubble.small .bubble-body {
      font-size: 11px;
    }
    .log-item {
      margin: 0 0 3px 0;
      padding: 3px 7px;
      border-radius: 8px;
      background: var(--log-bg);
      border: 1px solid var(--log-border);
      animation: logIn .18s ease-out;
    }
    .log-title {
      font-size: 9px;
      color: var(--log-title);
      margin-bottom: 0;
      line-height: 1.1;
    }
    .log-body {
      font-size: 10px;
      color: var(--log-text);
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.2;
    }
    .empty {
      padding: 3px;
      color: var(--empty);
      font-size: 10px;
    }
    ::-webkit-scrollbar {
      width: 10px;
      height: 10px;
    }
    ::-webkit-scrollbar-track {
      background: transparent;
    }
    ::-webkit-scrollbar-thumb {
      background: rgba(96, 108, 128, 0.7);
      border-radius: 5px;
    }
    @keyframes bubbleIn {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
    @keyframes logIn {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
  </style>
</head>
<body>
  <div id="app">
    <section class="panel">
      <div class="panel-title">关键信息</div>
      <div id="events" class="panel-body events-body"></div>
    </section>
    <section class="panel">
      <div class="panel-title">关键日志</div>
      <div class="logs-shell">
        <div id="logFilters" class="log-filters"></div>
        <div id="logs" class="panel-body logs-body"></div>
      </div>
    </section>
  </div>
  <script>
    const EMPTY_EVENTS = "等待 QA / 建议 / 规则消息…";
    const EMPTY_LOGS = "等待关键日志…";
    const LOG_FILTER_ORDER = ["all", "qa", "tts", "rules", "ai", "web", "startup", "other"];
    const LOG_FILTER_LABELS = {
      all: "全部",
      qa: "QA",
      tts: "TTS",
      rules: "Rules",
      ai: "AI",
      web: "Web",
      startup: "启动",
      other: "其他"
    };
    let currentState = { events: [], logs: [], alpha: 0.9, hit_alpha: 0.04 };
    let activeLogFilters = new Set(["all"]);

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function inferLogCategory(text) {
      const raw = String(text ?? "");
      if (raw.startsWith("[QA") || raw.includes("[QA ")) return "qa";
      if (raw.startsWith("[TTS") || raw.includes("[TTS")) return "tts";
      if (raw.startsWith("[Rules]")) return "rules";
      if (raw.startsWith("[AI worker]")) return "ai";
      if (raw.startsWith("[WebKnowledge")) return "web";
      if (raw.startsWith("[startup]")) return "startup";
      return "other";
    }

    function normalizeFilters() {
      if (!activeLogFilters.size) {
        activeLogFilters = new Set(["all"]);
        return;
      }
      if (activeLogFilters.has("all") && activeLogFilters.size > 1) {
        activeLogFilters.delete("all");
      }
      if (!activeLogFilters.size) {
        activeLogFilters = new Set(["all"]);
      }
    }

    function toggleFilter(name) {
      if (name === "all") {
        activeLogFilters = new Set(["all"]);
      } else {
        activeLogFilters.delete("all");
        if (activeLogFilters.has(name)) {
          activeLogFilters.delete(name);
        } else {
          activeLogFilters.add(name);
        }
        if (!activeLogFilters.size) {
          activeLogFilters = new Set(["all"]);
        }
      }
      renderFilters();
      renderLogs();
    }

    function renderFilters() {
      normalizeFilters();
      const filtersNode = document.getElementById("logFilters");
      filtersNode.innerHTML = LOG_FILTER_ORDER.map((name) => {
        const active = activeLogFilters.has(name) ? "active" : "";
        return `<button class="filter-chip ${active}" data-filter="${name}">${LOG_FILTER_LABELS[name]}</button>`;
      }).join("");
      filtersNode.querySelectorAll(".filter-chip").forEach((node) => {
        node.addEventListener("click", () => toggleFilter(node.dataset.filter));
      });
    }

    function renderEvents() {
      const events = Array.isArray(currentState.events) ? currentState.events : [];
      const eventsNode = document.getElementById("events");
      if (!events.length) {
        eventsNode.innerHTML = `<div class="empty">${escapeHtml(EMPTY_EVENTS)}</div>`;
      } else {
        eventsNode.innerHTML = events.map((entry) => {
          const align = entry.align === "right" ? "right" : "left";
          const cls = entry.small ? "bubble small" : "bubble";
          const countBadge = entry.count > 1
            ? `<span class="count-badge" style="background:${entry.badge_bg};color:${entry.title_color};">x${entry.count}</span>`
            : "";
          return `
            <div class="event-row ${align}">
              <div class="${cls}" style="background:${entry.bg};border-color:${entry.border};border-radius:${entry.radius};">
                <div class="bubble-title" style="color:${entry.title_color};">
                  <span>${escapeHtml(entry.at)} · ${escapeHtml(entry.label)}</span>
                  ${countBadge}
                </div>
                <div class="bubble-body" style="color:${entry.text_color};">${escapeHtml(entry.text)}</div>
              </div>
            </div>
          `;
        }).join("");
      }
      eventsNode.scrollTop = eventsNode.scrollHeight;
    }

    function renderLogs() {
      const logs = Array.isArray(currentState.logs) ? currentState.logs : [];
      const logsNode = document.getElementById("logs");
      const visibleLogs = activeLogFilters.has("all")
        ? logs
        : logs.filter((entry) => activeLogFilters.has(inferLogCategory(entry.text)));
      if (!visibleLogs.length) {
        logsNode.innerHTML = `<div class="empty">${escapeHtml(EMPTY_LOGS)}</div>`;
      } else {
        logsNode.innerHTML = visibleLogs.map((entry) => `
          <div class="log-item">
            <div class="log-title">${escapeHtml(entry.at)} · ${escapeHtml(LOG_FILTER_LABELS[inferLogCategory(entry.text)] || "日志")}</div>
            <div class="log-body">${escapeHtml(entry.text)}</div>
          </div>
        `).join("");
      }
      logsNode.scrollTop = logsNode.scrollHeight;
    }

    function renderState(state) {
      currentState = {
        events: Array.isArray(state.events) ? state.events : [],
        logs: Array.isArray(state.logs) ? state.logs : [],
        alpha: typeof state.alpha === "number" ? state.alpha : 0.9,
        hit_alpha: typeof state.hit_alpha === "number" ? state.hit_alpha : 0.04,
      };
      const alpha = currentState.alpha;
      const hit = currentState.hit_alpha;

      document.documentElement.style.setProperty("--content-alpha", String(alpha));
      document.documentElement.style.setProperty("--panel-bg", `rgba(8, 12, 18, ${hit})`);
      renderFilters();
      renderEvents();
      renderLogs();
    }

    window.renderOverlayState = renderState;
    window.renderOverlayEvents = function(events) {
      currentState.events = Array.isArray(events) ? events : [];
      renderEvents();
    };
    window.renderOverlayLogs = function(logs) {
      currentState.logs = Array.isArray(logs) ? logs : [];
      renderLogs();
    };
    window.renderOverlayChrome = function(alpha, hitAlpha) {
      if (typeof alpha === "number") {
        currentState.alpha = alpha;
        document.documentElement.style.setProperty("--content-alpha", String(alpha));
      }
      if (typeof hitAlpha === "number") {
        currentState.hit_alpha = hitAlpha;
        document.documentElement.style.setProperty("--panel-bg", `rgba(8, 12, 18, ${hitAlpha})`);
      }
    };
  </script>
</body>
</html>"""

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
        message_id = event.get("message_id")
        replace = bool(event.get("replace", False))
        if message_id is not None:
            item["message_id"] = str(message_id)
            item["final"] = bool(event.get("final", False))
        if kind == "log":
            self._log_entries.append(item)
            self._render_logs_only()
        else:
            replaced = False
            if replace and message_id is not None:
                for existing in self._event_entries:
                    if str(existing.get("message_id", "")) == str(message_id):
                        existing["kind"] = kind
                        existing["text"] = text
                        existing["at"] = item["at"]
                        existing["message_id"] = str(message_id)
                        existing["final"] = bool(event.get("final", False))
                        replaced = True
                        break
            if not replaced and self._event_entries:
                last = self._event_entries[-1]
                if str(last.get("kind")) == kind and str(last.get("text")) == text:
                    last["count"] = int(last.get("count", 1)) + 1
                    last["at"] = item["at"]
                else:
                    self._event_entries.append(item)
            elif not replaced:
                self._event_entries.append(item)
            self._render_events_only()

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
        self._render_overlay()

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

    def _serialize_events(self) -> list[dict[str, object]]:
        payload: list[dict[str, object]] = []
        for entry in self._event_entries:
            kind = str(entry["kind"])
            style = _KIND_STYLES.get(kind, _KIND_STYLES["game_ai"])
            if kind == "qa_output":
                radius = "16px 16px 16px 6px"
            elif kind in _RIGHT_ALIGNED_KINDS:
                radius = "16px 16px 6px 16px"
            else:
                radius = "16px 16px 16px 8px"
            payload.append(
                {
                    "kind": kind,
                    "label": _KIND_LABELS.get(kind, kind),
                    "text": str(entry["text"]),
                    "at": str(entry["at"]),
                    "count": int(entry.get("count", 1)),
                    "align": "right" if kind in _RIGHT_ALIGNED_KINDS else "left",
                    "small": bool(style["small"]),
                    "bg": self._rgba(style["bg"], 0.26 if style["small"] else 0.30),
                    "badge_bg": self._rgba(style["bg"], 0.42),
                    "border": style["border"],
                    "title_color": style["title"],
                    "text_color": style["text"],
                    "radius": radius,
                }
            )
        return payload

    def _serialize_logs(self) -> list[dict[str, str]]:
        return [
            {"at": str(entry["at"]), "text": str(entry["text"])}
            for entry in self._log_entries
        ]

    def _render_overlay(self):
        if not self._web_ready:
            return
        payload = {
            "events": self._serialize_events(),
            "logs": self._serialize_logs(),
            "alpha": round(self._content_alpha, 3),
            "hit_alpha": round(max(0.01, self._hit_test_alpha), 3),
        }
        js = f"window.renderOverlayState({json.dumps(payload, ensure_ascii=False)});"
        self._view.page().runJavaScript(js)

    def _render_events_only(self):
        if not self._web_ready:
            return
        js = f"window.renderOverlayEvents({json.dumps(self._serialize_events(), ensure_ascii=False)});"
        self._view.page().runJavaScript(js)

    def _render_logs_only(self):
        if not self._web_ready:
            return
        js = f"window.renderOverlayLogs({json.dumps(self._serialize_logs(), ensure_ascii=False)});"
        self._view.page().runJavaScript(js)

    def _on_web_load_finished(self, ok: bool):
        self._web_ready = bool(ok)
        if ok:
            self._render_overlay()

    def _rgba(self, rgb: tuple[int, int, int], alpha: float) -> str:
        value = max(0.10, min(1.0, alpha * self._content_alpha))
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {value:.3f})"

    def _apply_styles(self):
        hit_bg = self._rgba((8, 12, 18), self._hit_test_alpha)
        toolbar_bg = self._rgba((16, 22, 32), 0.18)
        button_bg = self._rgba((28, 38, 54), 0.72)
        button_hover_bg = self._rgba((43, 58, 80), 0.82)
        self._toolbar.setStyleSheet(
            f"QFrame#overlayToolbar {{ background:{toolbar_bg}; border: 1px solid rgba(82,96,120,160); border-radius:14px; }}"
            "QLabel { color:#eef3fb; background: transparent; }"
            f"QPushButton {{ background:{button_bg}; color:#dbe5f4; border:1px solid #3a4b63; border-radius:8px; padding:4px 10px; }}"
            f"QPushButton:hover {{ background:{button_hover_bg}; }}"
        )
        self.setStyleSheet(
            f"QWidget#overlayRoot {{ background:{hit_bg}; border:none; }}"
        )
        self._content_frame.setStyleSheet(
            f"QFrame#overlayContent {{ background:{hit_bg}; border:none; border-radius:14px; }}"
        )
        self._view.setStyleSheet("background: transparent; border: none;")
        if self._web_ready:
            js = (
                "window.renderOverlayChrome("
                f"{json.dumps(round(self._content_alpha, 3))}, "
                f"{json.dumps(round(max(0.01, self._hit_test_alpha), 3))}"
                ");"
            )
            self._view.page().runJavaScript(js)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._hit_test_edges(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._resize_edges and self._resize_start_global is not None and self._resize_start_geometry is not None:
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._resize_edges.clear()
        self._resize_start_global = None
        self._resize_start_geometry = None
        self._drag_pos = None
        pos = self.pos()
        self._pos_x = pos.x()
        self._pos_y = pos.y()
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 0.08 if event.angleDelta().y() > 0 else -0.08
            self._content_alpha = max(0.28, min(1.0, self._content_alpha + delta))
            self._apply_styles()
            event.accept()
            return
        super().wheelEvent(event)

    def leaveEvent(self, event):
        if not self._resize_edges:
            self.unsetCursor()
        super().leaveEvent(event)

    def _hit_test_edges(self, pos: QPoint) -> set[str]:
        rect = self.rect()
        edges: set[str] = set()
        if pos.x() <= _RESIZE_MARGIN:
            edges.add("left")
        elif pos.x() >= rect.width() - _RESIZE_MARGIN:
            edges.add("right")
        if pos.y() <= _RESIZE_MARGIN:
            edges.add("top")
        elif pos.y() >= rect.height() - _RESIZE_MARGIN:
            edges.add("bottom")
        return edges

    def _update_resize_cursor(self, pos: QPoint) -> None:
        edges = self._hit_test_edges(pos)
        if edges in ({"left", "top"}, {"right", "bottom"}):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in ({"right", "top"}, {"left", "bottom"}):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & {"left", "right"}:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges & {"top", "bottom"}:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def _perform_resize(self, global_pos: QPoint) -> None:
        if self._resize_start_global is None or self._resize_start_geometry is None:
            return
        delta = global_pos - self._resize_start_global
        geom = self._resize_start_geometry
        left = geom.left()
        top = geom.top()
        right = geom.right()
        bottom = geom.bottom()
        min_w = self.minimumWidth()
        min_h = self.minimumHeight()

        if "left" in self._resize_edges:
            left = min(left + delta.x(), right - min_w + 1)
        if "right" in self._resize_edges:
            right = max(right + delta.x(), left + min_w - 1)
        if "top" in self._resize_edges:
            top = min(top + delta.y(), bottom - min_h + 1)
        if "bottom" in self._resize_edges:
            bottom = max(bottom + delta.y(), top + min_h - 1)

        self.setGeometry(left, top, right - left + 1, bottom - top + 1)
        if not self._collapsed:
            self._expanded_size = (self.width(), self.height())
