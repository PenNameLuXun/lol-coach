# LOL Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows desktop app that captures League of Legends screenshots, sends them to a configurable AI provider, and reads advice aloud via TTS — running silently in the system tray with an optional UI.

**Architecture:** Single PyQt6 process with three daemon threads (capturer, AI, TTS) communicating via thread-safe queues. Qt Signals bridge backend events to UI components safely. Config is stored in `config.yaml` and hot-reloaded on file change.

**Tech Stack:** Python 3.11+, PyQt6, mss, Pillow, keyboard, anthropic, openai, google-generativeai, pyttsx3, edge-tts, pyyaml, sqlite3

---

## File Map

| File | Responsibility |
|------|---------------|
| `main.py` | Entry point: create QApplication, wire all components, start daemon threads |
| `config.example.yaml` | Annotated config template distributed with the repo |
| `src/config.py` | Load/save `config.yaml`, typed accessors, file-watcher hot-reload |
| `src/event_bus.py` | Two queues (`capture_queue`, `advice_queue`) + Qt Signal bridge |
| `src/history.py` | SQLite persistence: advice rows, session marking, text export |
| `src/ai_provider.py` | `BaseProvider` ABC + `ClaudeProvider`, `OpenAIProvider`, `GeminiProvider` |
| `src/capturer.py` | Screenshot thread: timer loop + global hotkey, compresses to JPEG |
| `src/tts_engine.py` | `BaseTTS` ABC + `WindowsTTS`, `EdgeTTS`, `OpenAITTS`; interrupt support |
| `src/ui/overlay.py` | Frameless always-on-top transparent window, fade timer, drag to move |
| `src/ui/tray.py` | System tray icon, right-click menu, 3-state icon color |
| `src/ui/tabs/config_tab.py` | PyQt6 form: provider/key/model/TTS/hotkeys/interval/prompt |
| `src/ui/tabs/log_tab.py` | Scrolling text view of advice with timestamp, clear button |
| `src/ui/tabs/history_tab.py` | Session-grouped list view, mark session, export button |
| `src/ui/main_window.py` | QMainWindow with 4 tabs, hidden by default |
| `tests/test_config.py` | Config load, save, defaults, hot-reload callback |
| `tests/test_event_bus.py` | Queue put/get, signal emission |
| `tests/test_history.py` | Insert, query by session, export |
| `tests/test_ai_provider.py` | Each provider with mocked SDK clients |
| `tests/test_capturer.py` | Timer trigger, hotkey trigger, JPEG compression with mocked mss |
| `tests/test_tts_engine.py` | speak() dispatch, interrupt logic with mocked backends |

---

## Task 1: Project Bootstrap

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `config.example.yaml`
- Create: `assets/icon_gen.py` (generates `assets/icon.png` programmatically)
- Create: `src/__init__.py`, `src/ui/__init__.py`, `src/ui/tabs/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/ui/tabs tests assets
touch src/__init__.py src/ui/__init__.py src/ui/tabs/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
PyQt6>=6.6.0
mss>=9.0.1
Pillow>=10.3.0
keyboard>=0.13.5
anthropic>=0.25.0
openai>=1.30.0
google-generativeai>=0.7.0
pyttsx3>=2.90
edge-tts>=6.1.9
pyyaml>=6.0.1
pytest>=8.2.0
pytest-mock>=3.14.0
```

- [ ] **Step 3: Write `.gitignore`**

```
config.yaml
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
*.db
```

- [ ] **Step 4: Write `config.example.yaml`**

```yaml
# LOL Coach Configuration
# Copy this file to config.yaml and fill in your API keys.

ai:
  # Active provider: claude | openai | gemini
  provider: claude

  system_prompt: "你是一个英雄联盟教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条对局建议。"

  claude:
    api_key: "your-anthropic-api-key-here"
    model: "claude-opus-4-6"
    max_tokens: 200
    temperature: 0.7

  openai:
    api_key: "your-openai-api-key-here"
    model: "gpt-4o"
    max_tokens: 200
    temperature: 0.7

  gemini:
    api_key: "your-google-api-key-here"
    model: "gemini-1.5-pro"
    max_tokens: 200
    temperature: 0.7

tts:
  # Active backend: windows | edge | openai
  backend: edge

  # Interrupt current speech when new advice arrives
  interrupt: true

  windows:
    rate: 180       # Words per minute
    volume: 1.0

  edge:
    voice: "zh-CN-XiaoxiaoNeural"

  openai:
    api_key: "your-openai-api-key-here"
    voice: "alloy"
    model: "tts-1"

capture:
  # Interval in seconds for automatic capture. 0 = disabled.
  interval: 5
  # Global hotkey for manual capture. Empty string = disabled.
  hotkey: "ctrl+shift+a"
  # Screenshot region: fullscreen | lol_window
  region: "fullscreen"
  # JPEG compression quality (1-95)
  jpeg_quality: 85

overlay:
  enabled: true
  x: 100
  y: 100
  # Seconds to display advice before fading. 0 = stay forever.
  fade_after: 8
  # Hotkey to toggle overlay visibility
  toggle_hotkey: "ctrl+shift+h"

app:
  start_minimized: true
```

- [ ] **Step 5: Generate placeholder icon `assets/icon_gen.py`**

```python
"""Run once to generate assets/icon.png"""
from PIL import Image, ImageDraw

img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([4, 4, 60, 60], fill=(34, 197, 94, 255))   # green circle
draw.polygon([(20, 44), (32, 20), (44, 44)], fill=(255, 255, 255, 230))  # white triangle
img.save("assets/icon.png")
print("icon.png generated")
```

- [ ] **Step 6: Run icon generator**

```bash
cd D:/groot/projects/playground/lol-coach
python assets/icon_gen.py
```

Expected output: `icon.png generated`

- [ ] **Step 7: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 8: Commit**

```bash
git init
git add requirements.txt .gitignore config.example.yaml assets/ src/__init__.py src/ui/__init__.py src/ui/tabs/__init__.py tests/__init__.py
git commit -m "chore: project bootstrap — structure, deps, config template, icon"
```

---

## Task 2: Config Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests `tests/test_config.py`**

```python
import os
import time
import tempfile
import pytest
import yaml
from src.config import Config

MINIMAL_CONFIG = {
    "ai": {
        "provider": "claude",
        "system_prompt": "test prompt",
        "claude": {"api_key": "k1", "model": "claude-opus-4-6", "max_tokens": 200, "temperature": 0.7},
        "openai": {"api_key": "k2", "model": "gpt-4o", "max_tokens": 200, "temperature": 0.7},
        "gemini": {"api_key": "k3", "model": "gemini-1.5-pro", "max_tokens": 200, "temperature": 0.7},
    },
    "tts": {
        "backend": "windows",
        "interrupt": True,
        "windows": {"rate": 180, "volume": 1.0},
        "edge": {"voice": "zh-CN-XiaoxiaoNeural"},
        "openai": {"api_key": "k4", "voice": "alloy", "model": "tts-1"},
    },
    "capture": {"interval": 5, "hotkey": "ctrl+shift+a", "region": "fullscreen", "jpeg_quality": 85},
    "overlay": {"enabled": True, "x": 100, "y": 100, "fade_after": 8, "toggle_hotkey": "ctrl+shift+h"},
    "app": {"start_minimized": True},
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(MINIMAL_CONFIG))
    return str(path)


def test_load_returns_correct_provider(config_file):
    cfg = Config(config_file)
    assert cfg.ai_provider == "claude"


def test_load_returns_api_key(config_file):
    cfg = Config(config_file)
    assert cfg.ai_config("claude")["api_key"] == "k1"


def test_load_tts_backend(config_file):
    cfg = Config(config_file)
    assert cfg.tts_backend == "windows"


def test_load_capture_interval(config_file):
    cfg = Config(config_file)
    assert cfg.capture_interval == 5


def test_save_roundtrip(config_file):
    cfg = Config(config_file)
    cfg.set("capture.interval", 10)
    cfg2 = Config(config_file)
    assert cfg2.capture_interval == 10


def test_hot_reload_calls_callback(config_file):
    cfg = Config(config_file)
    called = []
    cfg.on_reload(lambda: called.append(True))
    cfg._start_watcher()

    # Modify the file
    time.sleep(0.05)
    with open(config_file, "r") as f:
        data = yaml.safe_load(f)
    data["capture"]["interval"] = 99
    with open(config_file, "w") as f:
        yaml.dump(data, f)

    time.sleep(1.5)  # watcher polls every 1s
    cfg._stop_watcher()
    assert len(called) >= 1


def test_get_nested_key(config_file):
    cfg = Config(config_file)
    assert cfg.get("overlay.x") == 100


def test_system_prompt(config_file):
    cfg = Config(config_file)
    assert cfg.system_prompt == "test prompt"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: ImportError or multiple failures — `Config` not defined yet.

- [ ] **Step 3: Write `src/config.py`**

```python
import threading
import time
import yaml
from typing import Any, Callable


class Config:
    def __init__(self, path: str = "config.yaml"):
        self._path = path
        self._data: dict = {}
        self._callbacks: list[Callable] = []
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._mtime: float = 0.0
        self._load()

    # ── load / save ──────────────────────────────────────────────────────────

    def _load(self):
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        self._mtime = self._current_mtime()

    def _current_mtime(self) -> float:
        import os
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True)
        self._mtime = self._current_mtime()

    # ── typed accessors ───────────────────────────────────────────────────────

    @property
    def ai_provider(self) -> str:
        return self._data["ai"]["provider"]

    @property
    def system_prompt(self) -> str:
        return self._data["ai"]["system_prompt"]

    def ai_config(self, provider: str) -> dict:
        return self._data["ai"][provider]

    @property
    def tts_backend(self) -> str:
        return self._data["tts"]["backend"]

    def tts_config(self, backend: str) -> dict:
        return self._data["tts"].get(backend, {})

    @property
    def tts_interrupt(self) -> bool:
        return self._data["tts"].get("interrupt", True)

    @property
    def capture_interval(self) -> int:
        return self._data["capture"]["interval"]

    @property
    def capture_hotkey(self) -> str:
        return self._data["capture"].get("hotkey", "")

    @property
    def capture_region(self) -> str:
        return self._data["capture"].get("region", "fullscreen")

    @property
    def capture_jpeg_quality(self) -> int:
        return self._data["capture"].get("jpeg_quality", 85)

    @property
    def overlay(self) -> dict:
        return self._data.get("overlay", {})

    @property
    def start_minimized(self) -> bool:
        return self._data.get("app", {}).get("start_minimized", True)

    # ── generic get/set ───────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation access e.g. 'capture.interval'"""
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any):
        """Dot-notation write + save e.g. set('capture.interval', 10)"""
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    # ── hot-reload watcher ────────────────────────────────────────────────────

    def on_reload(self, callback: Callable):
        self._callbacks.append(callback)

    def _start_watcher(self):
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def _stop_watcher(self):
        self._stop_event.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=3)

    def _watch_loop(self):
        while not self._stop_event.wait(timeout=1.0):
            mtime = self._current_mtime()
            if mtime != self._mtime:
                self._load()
                for cb in self._callbacks:
                    cb()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_config.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: config module with typed accessors and hot-reload watcher"
```

---

## Task 3: Event Bus

**Files:**
- Create: `src/event_bus.py`
- Create: `tests/test_event_bus.py`

- [ ] **Step 1: Write failing tests `tests/test_event_bus.py`**

```python
import queue
import pytest
from unittest.mock import MagicMock
from src.event_bus import EventBus


def test_put_and_get_capture():
    bus = EventBus()
    bus.put_capture(b"img_bytes")
    assert bus.get_capture(timeout=0.1) == b"img_bytes"


def test_put_and_get_advice():
    bus = EventBus()
    bus.put_advice("attack dragon")
    assert bus.get_advice(timeout=0.1) == "attack dragon"


def test_get_capture_empty_raises():
    bus = EventBus()
    with pytest.raises(queue.Empty):
        bus.get_capture(timeout=0.05)


def test_get_advice_empty_raises():
    bus = EventBus()
    with pytest.raises(queue.Empty):
        bus.get_advice(timeout=0.05)


def test_emit_advice_calls_listeners():
    bus = EventBus()
    cb = MagicMock()
    bus.add_advice_listener(cb)
    bus.emit_advice("push mid")
    cb.assert_called_once_with("push mid")


def test_multiple_advice_listeners():
    bus = EventBus()
    cb1, cb2 = MagicMock(), MagicMock()
    bus.add_advice_listener(cb1)
    bus.add_advice_listener(cb2)
    bus.emit_advice("ward river")
    cb1.assert_called_once_with("ward river")
    cb2.assert_called_once_with("ward river")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_event_bus.py -v
```

Expected: ImportError — `EventBus` not defined.

- [ ] **Step 3: Write `src/event_bus.py`**

```python
import queue
from typing import Callable


class EventBus:
    """Thread-safe queues for image frames and advice text.

    capture_queue: bytes (JPEG image)
    advice_queue:  str   (advice text)

    Listeners registered via add_advice_listener() are called synchronously
    from whatever thread calls emit_advice(). UI components must connect via
    Qt Signals instead; this mechanism is for non-UI consumers (TTS, history).
    """

    def __init__(self):
        self._capture_q: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self._advice_q: queue.Queue[str] = queue.Queue(maxsize=10)
        self._advice_listeners: list[Callable[[str], None]] = []

    # ── capture queue ─────────────────────────────────────────────────────────

    def put_capture(self, image_bytes: bytes):
        """Non-blocking put; drops oldest frame if queue is full."""
        try:
            self._capture_q.put_nowait(image_bytes)
        except queue.Full:
            try:
                self._capture_q.get_nowait()
            except queue.Empty:
                pass
            self._capture_q.put_nowait(image_bytes)

    def get_capture(self, timeout: float = 1.0) -> bytes:
        return self._capture_q.get(timeout=timeout)

    # ── advice queue ──────────────────────────────────────────────────────────

    def put_advice(self, text: str):
        self._advice_q.put_nowait(text)

    def get_advice(self, timeout: float = 1.0) -> str:
        return self._advice_q.get(timeout=timeout)

    # ── listener pattern (for non-Qt consumers) ───────────────────────────────

    def add_advice_listener(self, callback: Callable[[str], None]):
        self._advice_listeners.append(callback)

    def emit_advice(self, text: str):
        """Call all registered listeners with the advice text."""
        for cb in self._advice_listeners:
            cb(text)

    # ── public queue accessors ────────────────────────────────────────────────

    @property
    def capture_queue(self) -> queue.Queue:
        return self._capture_q
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_event_bus.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/event_bus.py tests/test_event_bus.py
git commit -m "feat: event bus with capture/advice queues and listener pattern"
```

---

## Task 4: History Module

**Files:**
- Create: `src/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing tests `tests/test_history.py`**

```python
import os
import pytest
from src.history import History


@pytest.fixture
def db(tmp_path):
    h = History(str(tmp_path / "test.db"))
    yield h
    h.close()


def test_add_and_list_advice(db):
    db.add_advice("push top", "timer")
    rows = db.list_advice()
    assert len(rows) == 1
    assert rows[0]["text"] == "push top"
    assert rows[0]["trigger"] == "timer"


def test_multiple_advice(db):
    db.add_advice("ward river", "hotkey")
    db.add_advice("recall now", "timer")
    rows = db.list_advice()
    assert len(rows) == 2


def test_session_grouping(db):
    session_id = db.start_session()
    db.add_advice("push mid", "timer", session_id=session_id)
    db.end_session(session_id)
    sessions = db.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    rows = db.list_advice(session_id=session_id)
    assert len(rows) == 1
    assert rows[0]["text"] == "push mid"


def test_export_text(db):
    session_id = db.start_session()
    db.add_advice("attack baron", "timer", session_id=session_id)
    db.end_session(session_id)
    text = db.export_session(session_id)
    assert "attack baron" in text


def test_advice_without_session(db):
    db.add_advice("buy item", "hotkey")
    rows = db.list_advice(session_id=None)
    assert any(r["text"] == "buy item" for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_history.py -v
```

Expected: ImportError — `History` not defined.

- [ ] **Step 3: Write `src/history.py`**

```python
import sqlite3
from datetime import datetime
from typing import Optional


class History:
    def __init__(self, db_path: str = "lol_coach.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                started TEXT NOT NULL,
                ended   TEXT
            );
            CREATE TABLE IF NOT EXISTS advice (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER REFERENCES sessions(id),
                timestamp  TEXT NOT NULL,
                text       TEXT NOT NULL,
                trigger    TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── sessions ──────────────────────────────────────────────────────────────

    def start_session(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started) VALUES (?)",
            (datetime.now().isoformat(),)
        )
        self._conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int):
        self._conn.execute(
            "UPDATE sessions SET ended = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        self._conn.commit()

    def list_sessions(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM sessions ORDER BY started DESC")
        return [dict(row) for row in cur.fetchall()]

    # ── advice ────────────────────────────────────────────────────────────────

    def add_advice(self, text: str, trigger: str, session_id: Optional[int] = None):
        self._conn.execute(
            "INSERT INTO advice (session_id, timestamp, text, trigger) VALUES (?, ?, ?, ?)",
            (session_id, datetime.now().isoformat(), text, trigger)
        )
        self._conn.commit()

    def list_advice(self, session_id: Optional[int] = None) -> list[dict]:
        if session_id is not None:
            cur = self._conn.execute(
                "SELECT * FROM advice WHERE session_id = ? ORDER BY timestamp",
                (session_id,)
            )
        else:
            cur = self._conn.execute("SELECT * FROM advice ORDER BY timestamp")
        return [dict(row) for row in cur.fetchall()]

    # ── export ────────────────────────────────────────────────────────────────

    def export_session(self, session_id: int) -> str:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        lines = [f"=== 场次 {session_id} | 开始: {rows['started']} 结束: {rows['ended'] or '进行中'} ==="]
        for row in self.list_advice(session_id=session_id):
            lines.append(f"[{row['timestamp']}] ({row['trigger']}) {row['text']}")
        return "\n".join(lines)

    def close(self):
        self._conn.close()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_history.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/history.py tests/test_history.py
git commit -m "feat: history module with SQLite, session grouping and text export"
```

---

## Task 5: AI Provider Module

**Files:**
- Create: `src/ai_provider.py`
- Create: `tests/test_ai_provider.py`

- [ ] **Step 1: Write failing tests `tests/test_ai_provider.py`**

```python
import pytest
from unittest.mock import MagicMock, patch
from src.ai_provider import ClaudeProvider, OpenAIProvider, GeminiProvider, get_provider


FAKE_IMAGE = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG bytes
PROMPT = "给出对局建议"


# ── ClaudeProvider ────────────────────────────────────────────────────────────

def test_claude_analyze_returns_text():
    with patch("src.ai_provider.anthropic.Anthropic") as MockClient:
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="push top lane")]
        MockClient.return_value.messages.create.return_value = mock_msg

        provider = ClaudeProvider(api_key="k", model="claude-opus-4-6", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "push top lane"


def test_claude_passes_correct_model():
    with patch("src.ai_provider.anthropic.Anthropic") as MockClient:
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="ok")]
        MockClient.return_value.messages.create.return_value = mock_msg

        provider = ClaudeProvider(api_key="k", model="claude-opus-4-6", max_tokens=50, temperature=0.5)
        provider.analyze(FAKE_IMAGE, PROMPT)
        call_kwargs = MockClient.return_value.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 50


# ── OpenAIProvider ────────────────────────────────────────────────────────────

def test_openai_analyze_returns_text():
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        choice = MagicMock()
        choice.message.content = "ward river"
        MockClient.return_value.chat.completions.create.return_value.choices = [choice]

        provider = OpenAIProvider(api_key="k", model="gpt-4o", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "ward river"


# ── GeminiProvider ────────────────────────────────────────────────────────────

def test_gemini_analyze_returns_text():
    with patch("src.ai_provider.genai") as mock_genai:
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = "recall now"
        mock_genai.GenerativeModel.return_value = mock_model

        provider = GeminiProvider(api_key="k", model="gemini-1.5-pro", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "recall now"


# ── Factory ───────────────────────────────────────────────────────────────────

def test_get_provider_returns_claude():
    with patch("src.ai_provider.anthropic.Anthropic"):
        cfg = {"api_key": "k", "model": "claude-opus-4-6", "max_tokens": 100, "temperature": 0.7}
        p = get_provider("claude", cfg)
        assert isinstance(p, ClaudeProvider)


def test_get_provider_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("unknown_llm", {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ai_provider.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `src/ai_provider.py`**

```python
import base64
from abc import ABC, abstractmethod

import anthropic
import openai
import google.generativeai as genai


class BaseProvider(ABC):
    @abstractmethod
    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        """Send image + prompt to AI; return advice string."""


class ClaudeProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return msg.content[0].text


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.choices[0].message.content


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        resp = self._model.generate_content(
            [prompt, img],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        return resp.text


def get_provider(name: str, cfg: dict) -> BaseProvider:
    providers = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
    }
    if name not in providers:
        raise ValueError(f"Unknown provider: {name}")
    return providers[name](
        api_key=cfg["api_key"],
        model=cfg["model"],
        max_tokens=cfg["max_tokens"],
        temperature=cfg["temperature"],
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ai_provider.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_provider.py tests/test_ai_provider.py
git commit -m "feat: AI provider abstraction with Claude, OpenAI, Gemini implementations"
```

---

## Task 6: Capturer Module

**Files:**
- Create: `src/capturer.py`
- Create: `tests/test_capturer.py`

- [ ] **Step 1: Write failing tests `tests/test_capturer.py`**

```python
import time
import queue
import pytest
from unittest.mock import MagicMock, patch
from src.capturer import Capturer


@pytest.fixture
def mock_mss():
    """Patch mss to return a fake screenshot."""
    with patch("src.capturer.mss.mss") as mock:
        fake_shot = MagicMock()
        fake_shot.rgb = b"\xff\x00\x00" * (1920 * 1080)
        fake_shot.size = (1920, 1080)
        mock.return_value.__enter__.return_value.grab.return_value = fake_shot
        yield mock


def test_capture_once_puts_bytes_in_queue(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=0, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.capture_once()
    assert not q.empty()
    data = q.get_nowait()
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_timer_captures_after_interval(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=1, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.start()
    time.sleep(1.6)
    cap.stop()
    assert not q.empty()


def test_stop_prevents_further_capture(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=1, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.start()
    time.sleep(0.2)
    cap.stop()
    q.queue.clear()
    time.sleep(1.5)
    assert q.empty()


def test_jpeg_quality_affects_size(mock_mss):
    q_high: queue.Queue[bytes] = queue.Queue()
    q_low: queue.Queue[bytes] = queue.Queue()
    cap_high = Capturer(capture_queue=q_high, interval=0, hotkey="", region="fullscreen", jpeg_quality=95)
    cap_low = Capturer(capture_queue=q_low, interval=0, hotkey="", region="fullscreen", jpeg_quality=10)
    cap_high.capture_once()
    cap_low.capture_once()
    assert len(q_high.get_nowait()) > len(q_low.get_nowait())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_capturer.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `src/capturer.py`**

```python
import io
import queue
import threading
from typing import Callable

import mss
import mss.tools
from PIL import Image


class Capturer:
    """Captures screenshots and puts JPEG bytes into capture_queue.

    Two trigger modes (can run simultaneously):
    - Timer: captures every `interval` seconds when interval > 0
    - Hotkey: calls capture_once() when global hotkey pressed (registered externally)
    """

    def __init__(
        self,
        capture_queue: queue.Queue,
        interval: int,
        hotkey: str,
        region: str,
        jpeg_quality: int,
    ):
        self._queue = capture_queue
        self._interval = interval
        self._hotkey = hotkey
        self._region = region
        self._jpeg_quality = jpeg_quality
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._hotkey_registered = False

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start timer-based capture thread and register hotkey."""
        if self._interval > 0:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._timer_loop, daemon=True)
            self._thread.start()
        if self._hotkey:
            self._register_hotkey()

    def stop(self):
        self._stop_event.set()
        if self._hotkey_registered:
            self._unregister_hotkey()
        if self._thread:
            self._thread.join(timeout=self._interval + 2)

    def capture_once(self):
        """Take one screenshot and put JPEG bytes into the queue."""
        jpeg = self._take_screenshot()
        try:
            self._queue.put_nowait(jpeg)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(jpeg)

    # ── internals ─────────────────────────────────────────────────────────────

    def _timer_loop(self):
        while not self._stop_event.wait(timeout=self._interval):
            self.capture_once()

    def _take_screenshot(self) -> bytes:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # full screen (index 0 = all monitors combined)
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self._jpeg_quality)
            return buf.getvalue()

    def _register_hotkey(self):
        try:
            import keyboard
            keyboard.add_hotkey(self._hotkey, self.capture_once)
            self._hotkey_registered = True
        except Exception:
            pass  # keyboard may require elevated permissions

    def _unregister_hotkey(self):
        try:
            import keyboard
            keyboard.remove_hotkey(self._hotkey)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_capturer.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capturer.py tests/test_capturer.py
git commit -m "feat: capturer module with timer loop, hotkey trigger and JPEG compression"
```

---

## Task 7: TTS Engine Module

**Files:**
- Create: `src/tts_engine.py`
- Create: `tests/test_tts_engine.py`

- [ ] **Step 1: Write failing tests `tests/test_tts_engine.py`**

```python
import pytest
from unittest.mock import MagicMock, patch, call
from src.tts_engine import WindowsTTS, EdgeTTS, OpenAITTS, get_tts_engine


def test_windows_tts_calls_say_and_runAndWait():
    with patch("src.tts_engine.pyttsx3.init") as mock_init:
        engine = MagicMock()
        mock_init.return_value = engine
        tts = WindowsTTS(rate=180, volume=1.0)
        tts.speak("push mid")
        engine.say.assert_called_once_with("push mid")
        engine.runAndWait.assert_called_once()


def test_windows_tts_stop_called_on_interrupt():
    with patch("src.tts_engine.pyttsx3.init") as mock_init:
        engine = MagicMock()
        mock_init.return_value = engine
        tts = WindowsTTS(rate=180, volume=1.0)
        tts.interrupt()
        engine.stop.assert_called_once()


def test_edge_tts_speak_calls_asyncio_run():
    with patch("src.tts_engine.asyncio.run") as mock_run:
        with patch("src.tts_engine.subprocess.run"):
            tts = EdgeTTS(voice="zh-CN-XiaoxiaoNeural")
            tts.speak("ward river")
            assert mock_run.called


def test_openai_tts_streams_audio():
    with patch("src.tts_engine.openai.OpenAI") as MockClient:
        mock_response = MagicMock()
        MockClient.return_value.audio.speech.create.return_value = mock_response
        with patch("src.tts_engine.subprocess.run"):
            tts = OpenAITTS(api_key="k", voice="alloy", model="tts-1")
            tts.speak("recall now")
            MockClient.return_value.audio.speech.create.assert_called_once()


def test_get_tts_engine_windows():
    with patch("src.tts_engine.pyttsx3.init"):
        engine = get_tts_engine("windows", {"rate": 180, "volume": 1.0})
        assert isinstance(engine, WindowsTTS)


def test_get_tts_engine_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown TTS backend"):
        get_tts_engine("unknown_tts", {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tts_engine.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write `src/tts_engine.py`**

```python
import asyncio
import io
import subprocess
import tempfile
from abc import ABC, abstractmethod

import pyttsx3
import openai


class BaseTTS(ABC):
    @abstractmethod
    def speak(self, text: str): ...

    def interrupt(self): ...  # optional: stop current playback


class WindowsTTS(BaseTTS):
    def __init__(self, rate: int, volume: float):
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)

    def speak(self, text: str):
        self._engine.say(text)
        self._engine.runAndWait()

    def interrupt(self):
        self._engine.stop()


class EdgeTTS(BaseTTS):
    def __init__(self, voice: str):
        self._voice = voice

    def speak(self, text: str):
        asyncio.run(self._async_speak(text))

    async def _async_speak(self, text: str):
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        communicate = edge_tts.Communicate(text, self._voice)
        await communicate.save(tmp_path)
        subprocess.run(["powershell", "-c", f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()'],
                       capture_output=True)


class OpenAITTS(BaseTTS):
    def __init__(self, api_key: str, voice: str, model: str):
        self._client = openai.OpenAI(api_key=api_key)
        self._voice = voice
        self._model = model

    def speak(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        response = self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
        )
        response.stream_to_file(tmp_path)
        subprocess.run(["powershell", "-c", f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()'],
                       capture_output=True)


def get_tts_engine(backend: str, cfg: dict) -> BaseTTS:
    if backend == "windows":
        return WindowsTTS(rate=cfg.get("rate", 180), volume=cfg.get("volume", 1.0))
    if backend == "edge":
        return EdgeTTS(voice=cfg.get("voice", "zh-CN-XiaoxiaoNeural"))
    if backend == "openai":
        return OpenAITTS(api_key=cfg["api_key"], voice=cfg.get("voice", "alloy"), model=cfg.get("model", "tts-1"))
    raise ValueError(f"Unknown TTS backend: {backend}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tts_engine.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tts_engine.py tests/test_tts_engine.py
git commit -m "feat: TTS engine with Windows/Edge/OpenAI backends and interrupt support"
```

---

## Task 8: Overlay Window

**Files:**
- Create: `src/ui/overlay.py`

- [ ] **Step 1: Write `src/ui/overlay.py`**

```python
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

    # ── public API ────────────────────────────────────────────────────────────

    def show_advice(self, text: str):
        self._label.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        if self._fade_after > 0:
            self._fade_timer.start(self._fade_after * 1000)

    def move_to(self, x: int, y: int):
        self.move(x, y)

    # ── drag support ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
```

- [ ] **Step 2: Smoke test (manual)**

No automated test for pure UI widgets. After `main.py` is wired up (Task 14), verify overlay appears over the game window.

- [ ] **Step 3: Commit**

```bash
git add src/ui/overlay.py
git commit -m "feat: overlay window — frameless, always-on-top, drag-to-reposition, auto-fade"
```

---

## Task 9: System Tray

**Files:**
- Create: `src/ui/tray.py`

- [ ] **Step 1: Write `src/ui/tray.py`**

```python
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
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

    # States
    STATE_PAUSED = "paused"
    STATE_RUNNING = "running"
    STATE_BUSY = "busy"

    _STATE_COLORS = {
        STATE_PAUSED: "#9ca3af",   # gray
        STATE_RUNNING: "#22c55e",  # green
        STATE_BUSY: "#f59e0b",     # yellow
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
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/tray.py
git commit -m "feat: system tray icon with 3-state color and right-click menu"
```

---

## Task 10: Config Tab

**Files:**
- Create: `src/ui/tabs/config_tab.py`

- [ ] **Step 1: Write `src/ui/tabs/config_tab.py`**

```python
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QPushButton, QTextEdit, QLabel, QGroupBox, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal
from src.config import Config


class ConfigTab(QWidget):
    """Form for editing all config.yaml settings.

    Emits `config_changed` after saving so other components can react.
    """

    config_changed = pyqtSignal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── AI ────────────────────────────────────────────────────────────────
        ai_box = QGroupBox("AI 设置")
        ai_form = QFormLayout(ai_box)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["claude", "openai", "gemini"])
        self._provider_combo.currentTextChanged.connect(self._update_api_key_label)
        ai_form.addRow("AI 提供商:", self._provider_combo)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        ai_form.addRow("API Key:", self._api_key_edit)

        self._model_edit = QLineEdit()
        ai_form.addRow("模型名称:", self._model_edit)

        self._prompt_edit = QTextEdit()
        self._prompt_edit.setMaximumHeight(80)
        ai_form.addRow("System Prompt:", self._prompt_edit)

        root.addWidget(ai_box)

        # ── TTS ───────────────────────────────────────────────────────────────
        tts_box = QGroupBox("语音输出")
        tts_form = QFormLayout(tts_box)

        self._tts_combo = QComboBox()
        self._tts_combo.addItems(["windows", "edge", "openai"])
        tts_form.addRow("TTS 后端:", self._tts_combo)

        root.addWidget(tts_box)

        # ── Capture ───────────────────────────────────────────────────────────
        cap_box = QGroupBox("截图设置")
        cap_form = QFormLayout(cap_box)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 60)
        self._interval_spin.setSuffix(" 秒 (0=禁用)")
        cap_form.addRow("定时间隔:", self._interval_spin)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("e.g. ctrl+shift+a  (空=禁用)")
        cap_form.addRow("截图热键:", self._hotkey_edit)

        self._region_combo = QComboBox()
        self._region_combo.addItems(["fullscreen", "lol_window"])
        cap_form.addRow("截图区域:", self._region_combo)

        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(10, 95)
        cap_form.addRow("JPEG 质量:", self._quality_spin)

        root.addWidget(cap_box)

        # ── Overlay ───────────────────────────────────────────────────────────
        ov_box = QGroupBox("悬浮窗")
        ov_form = QFormLayout(ov_box)

        self._fade_spin = QSpinBox()
        self._fade_spin.setRange(0, 60)
        self._fade_spin.setSuffix(" 秒 (0=不淡出)")
        ov_form.addRow("自动淡出:", self._fade_spin)

        self._overlay_hotkey_edit = QLineEdit()
        ov_form.addRow("显示/隐藏热键:", self._overlay_hotkey_edit)

        root.addWidget(ov_box)

        # ── Save button ───────────────────────────────────────────────────────
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)

    def _load_values(self):
        self._provider_combo.setCurrentText(self._cfg.ai_provider)
        provider = self._cfg.ai_provider
        self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
        self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        self._prompt_edit.setPlainText(self._cfg.system_prompt)
        self._tts_combo.setCurrentText(self._cfg.tts_backend)
        self._interval_spin.setValue(self._cfg.capture_interval)
        self._hotkey_edit.setText(self._cfg.capture_hotkey)
        self._region_combo.setCurrentText(self._cfg.capture_region)
        self._quality_spin.setValue(self._cfg.capture_jpeg_quality)
        self._fade_spin.setValue(self._cfg.overlay.get("fade_after", 8))
        self._overlay_hotkey_edit.setText(self._cfg.overlay.get("toggle_hotkey", ""))

    def _update_api_key_label(self, provider: str):
        try:
            self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
            self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        except KeyError:
            pass

    def _save(self):
        provider = self._provider_combo.currentText()
        self._cfg.set("ai.provider", provider)
        self._cfg.set(f"ai.{provider}.api_key", self._api_key_edit.text())
        self._cfg.set(f"ai.{provider}.model", self._model_edit.text())
        self._cfg.set("ai.system_prompt", self._prompt_edit.toPlainText())
        self._cfg.set("tts.backend", self._tts_combo.currentText())
        self._cfg.set("capture.interval", self._interval_spin.value())
        self._cfg.set("capture.hotkey", self._hotkey_edit.text())
        self._cfg.set("capture.region", self._region_combo.currentText())
        self._cfg.set("capture.jpeg_quality", self._quality_spin.value())
        self._cfg.set("overlay.fade_after", self._fade_spin.value())
        self._cfg.set("overlay.toggle_hotkey", self._overlay_hotkey_edit.text())
        self.config_changed.emit()
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/tabs/config_tab.py
git commit -m "feat: config tab — full settings form with save to config.yaml"
```

---

## Task 11: Log Tab

**Files:**
- Create: `src/ui/tabs/log_tab.py`

- [ ] **Step 1: Write `src/ui/tabs/log_tab.py`**

```python
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
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
        # auto-scroll to bottom
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/tabs/log_tab.py
git commit -m "feat: log tab — scrolling real-time advice log with clear button"
```

---

## Task 12: History Tab

**Files:**
- Create: `src/ui/tabs/history_tab.py`

- [ ] **Step 1: Write `src/ui/tabs/history_tab.py`**

```python
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

        # Left: session list
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

        # Right: advice detail
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
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/tabs/history_tab.py
git commit -m "feat: history tab — session list, detail view, session marking and export"
```

---

## Task 13: Main Window

**Files:**
- Create: `src/ui/main_window.py`

- [ ] **Step 1: Write `src/ui/main_window.py`**

```python
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
from PyQt6.QtCore import pyqtSlot
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

        about_widget = QWidget()
        tabs.addTab(self.config_tab, "配置")
        tabs.addTab(self.log_tab, "实时日志")
        tabs.addTab(self.history_tab, "对局历史")
        tabs.addTab(about_widget, "关于")

        self._build_about(about_widget)

    def _build_about(self, widget: QWidget):
        from PyQt6.QtWidgets import QVBoxLayout, QLabel
        from PyQt6.QtCore import Qt
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel("LOL Coach v0.1.0"))
        layout.addWidget(QLabel("快捷键：见配置页"))
        layout.addWidget(QLabel("截图 → AI分析 → 语音建议"))

    @pyqtSlot(str)
    def on_advice(self, text: str):
        """Connected to AI thread signal; update log tab."""
        self.log_tab.append_advice(text)
        self.history_tab.refresh()

    def closeEvent(self, event):
        """Hide to tray instead of closing."""
        event.ignore()
        self.hide()
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/main_window.py
git commit -m "feat: main window with 4 tabs, hides to tray on close"
```

---

## Task 14: Entry Point and Integration

**Files:**
- Create: `main.py`

- [ ] **Step 1: Write `main.py`**

```python
"""LOL Coach — entry point.

Wires all components together:
- Config → loaded from config.yaml (copied from config.example.yaml on first run)
- EventBus → shared queues between threads
- Capturer → screenshot daemon thread
- AI worker thread → consumes capture_queue, produces advice
- TTS worker thread → consumes advice_queue
- History → SQLite, accessed from main thread via signals
- UI → MainWindow (hidden), TrayIcon, OverlayWindow
"""

import queue
import shutil
import sys
import threading
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from src.config import Config
from src.event_bus import EventBus
from src.history import History
from src.capturer import Capturer
from src.ai_provider import get_provider
from src.tts_engine import get_tts_engine
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow


# ── Qt Signal bridge from worker threads to UI ────────────────────────────────

class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)


# ── Worker threads ─────────────────────────────────────────────────────────────

def ai_worker(bus: EventBus, config: Config, bridge: SignalBridge, stop_event: threading.Event, tray: TrayIcon):
    while not stop_event.is_set():
        try:
            image_bytes = bus.get_capture(timeout=1.0)
        except queue.Empty:
            continue
        try:
            tray.set_state(TrayIcon.STATE_BUSY)
            provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
            text = provider.analyze(image_bytes, config.system_prompt)
            bus.put_advice(text)
            bus.emit_advice(text)
            bridge.advice_ready.emit(text)
            tray.set_state(TrayIcon.STATE_RUNNING)
        except Exception as e:
            print(f"[AI worker error] {e}")
            tray.set_state(TrayIcon.STATE_RUNNING)


def tts_worker(bus: EventBus, config: Config, stop_event: threading.Event):
    current_engine = None

    def get_engine():
        return get_tts_engine(config.tts_backend, config.tts_config(config.tts_backend))

    while not stop_event.is_set():
        try:
            text = bus.get_advice(timeout=1.0)
        except queue.Empty:
            continue
        try:
            engine = get_engine()
            if config.tts_interrupt and current_engine:
                current_engine.interrupt()
            current_engine = engine
            engine.speak(text)
        except Exception as e:
            print(f"[TTS worker error] {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Bootstrap config
    if not os.path.exists("config.yaml"):
        shutil.copy("config.example.yaml", "config.yaml")
        print("Created config.yaml from template — please add your API keys.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in tray

    config = Config("config.yaml")
    config._start_watcher()

    bus = EventBus()
    history = History("lol_coach.db")

    bridge = SignalBridge()
    stop_event = threading.Event()
    running = [False]

    # ── UI ────────────────────────────────────────────────────────────────────
    overlay = OverlayWindow(fade_after=config.overlay.get("fade_after", 8))
    overlay.move_to(config.overlay.get("x", 100), config.overlay.get("y", 100))

    window = MainWindow(config, history)
    tray = TrayIcon("assets/icon.png")
    tray.show()

    # ── Signals ───────────────────────────────────────────────────────────────
    def on_advice(text: str):
        overlay.show_advice(text)
        window.on_advice(text)
        session_id = window.history_tab.get_current_session_id()
        history.add_advice(text, "timer", session_id=session_id)

    bridge.advice_ready.connect(on_advice)

    # ── Capturer ──────────────────────────────────────────────────────────────
    capturer = Capturer(
        capture_queue=bus.capture_queue,
        interval=config.capture_interval,
        hotkey=config.capture_hotkey,
        region=config.capture_region,
        jpeg_quality=config.capture_jpeg_quality,
    )

    # Register overlay toggle hotkey
    overlay_hotkey = config.overlay.get("toggle_hotkey", "")
    if overlay_hotkey:
        try:
            import keyboard
            keyboard.add_hotkey(overlay_hotkey, lambda: overlay.setVisible(not overlay.isVisible()))
        except Exception:
            pass

    # ── Start / Pause ─────────────────────────────────────────────────────────
    ai_thread: threading.Thread | None = None
    tts_thread: threading.Thread | None = None

    def start_analysis():
        nonlocal ai_thread, tts_thread
        if running[0]:
            return
        running[0] = True
        stop_event.clear()
        capturer.start()
        ai_thread = threading.Thread(target=ai_worker, args=(bus, config, bridge, stop_event, tray), daemon=True)
        tts_thread = threading.Thread(target=tts_worker, args=(bus, config, stop_event), daemon=True)
        ai_thread.start()
        tts_thread.start()
        tray.set_state(TrayIcon.STATE_RUNNING)

    def pause_analysis():
        if not running[0]:
            return
        running[0] = False
        capturer.stop()
        stop_event.set()
        tray.set_state(TrayIcon.STATE_PAUSED)

    def toggle():
        if running[0]:
            pause_analysis()
        else:
            start_analysis()

    tray.toggle_requested.connect(toggle)
    tray.open_window_requested.connect(window.show)
    tray.quit_requested.connect(lambda: (pause_analysis(), config._stop_watcher(), app.quit()))

    # Auto-start
    if not config.start_minimized:
        window.show()
    start_analysis()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run smoke test**

```bash
cd D:/groot/projects/playground/lol-coach
python main.py
```

Expected: tray icon appears (green), overlay hidden. Right-click tray → "打开主窗口" opens the 4-tab window. No crash.

> If `config.yaml` has placeholder API keys, AI analysis will fail gracefully (error printed to console). That's expected — add real keys to test end-to-end.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: entry point — wires capturer/AI/TTS threads, tray, overlay, main window"
```

---

## Task 15: End-to-End Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (test_config, test_event_bus, test_history, test_ai_provider, test_capturer, test_tts_engine).

- [ ] **Step 2: Configure real API key**

Edit `config.yaml`, set a real `claude.api_key` (or `openai.api_key`). Set `capture.interval: 10`.

- [ ] **Step 3: Launch and verify full flow**

```bash
python main.py
```

Checklist:
- [ ] Tray icon appears green
- [ ] After ~10 seconds, a screenshot is taken (check console for AI worker activity)
- [ ] AI advice is spoken aloud via TTS
- [ ] Advice appears in overlay window
- [ ] Advice appears in "实时日志" tab
- [ ] Start a session in "对局历史" tab; advice rows appear after starting
- [ ] Pause via tray → icon turns gray → no more captures
- [ ] Resume → icon turns green again
- [ ] Config tab: change interval to 30, save → live-reloads without restart

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: end-to-end verification complete"
```
