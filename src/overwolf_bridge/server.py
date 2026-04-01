from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from src.overwolf_bridge.models import OverwolfEvent, OverwolfSnapshot


class OverwolfBridgeServer:
    """Receives local Overwolf bridge payloads and exposes latest per-game snapshots."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7799, stale_after_seconds: int = 5):
        self.host = host
        self.port = port
        self.stale_after_seconds = max(1, int(stale_after_seconds))
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._snapshots: dict[str, OverwolfSnapshot] = {}
        self._events: dict[str, deque[OverwolfEvent]] = defaultdict(lambda: deque(maxlen=100))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path != "/health":
                    self.send_error(404, "Not found")
                    return
                payload = {
                    "ok": True,
                    "connected_games": server.connected_games(),
                }
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(content_length)
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self.send_error(400, "Invalid JSON")
                    return

                try:
                    if self.path == "/snapshot":
                        server.ingest_snapshot(payload)
                    elif self.path == "/event":
                        server.ingest_event(payload)
                    else:
                        self.send_error(404, "Not found")
                        return
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return

                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()
            self._events.clear()

    @property
    def is_connected(self) -> bool:
        return bool(self.connected_games())

    def connected_games(self) -> list[str]:
        with self._lock:
            return [
                game_id
                for game_id, snapshot in self._snapshots.items()
                if not self._is_stale(snapshot.timestamp)
            ]

    def is_game_connected(self, game_id: str) -> bool:
        snapshot = self.latest_snapshot(game_id)
        return snapshot is not None

    def latest_snapshot(self, game_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._snapshots.get(game_id)
            if snapshot is None or self._is_stale(snapshot.timestamp):
                return None
            return dict(snapshot.data)

    def latest_events(self, game_id: str, since: datetime | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events.get(game_id, ()))
        result: list[dict[str, Any]] = []
        for event in events:
            if since is not None and event.timestamp <= since:
                continue
            result.append(
                {
                    "game_id": event.game_id,
                    "event": event.event,
                    "data": dict(event.data),
                    "timestamp": event.timestamp.isoformat(),
                    "source": event.source,
                }
            )
        return result

    def ingest_snapshot(self, payload: dict[str, Any]) -> None:
        game_id = str(payload.get("game_id", "")).strip().lower()
        if not game_id:
            raise ValueError("Missing game_id")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Missing snapshot data")
        snapshot = OverwolfSnapshot(
            game_id=game_id,
            data=dict(data),
            timestamp=self._parse_timestamp(payload.get("timestamp")),
            source=str(payload.get("source", "overwolf")),
        )
        with self._lock:
            self._snapshots[game_id] = snapshot

    def ingest_event(self, payload: dict[str, Any]) -> None:
        game_id = str(payload.get("game_id", "")).strip().lower()
        event_name = str(payload.get("event", "")).strip()
        if not game_id or not event_name:
            raise ValueError("Missing game_id or event")
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        event = OverwolfEvent(
            game_id=game_id,
            event=event_name,
            data=dict(data),
            timestamp=self._parse_timestamp(payload.get("timestamp")),
            source=str(payload.get("source", "overwolf")),
        )
        with self._lock:
            self._events[game_id].append(event)

    def _is_stale(self, timestamp: datetime) -> bool:
        return datetime.utcnow() - timestamp > timedelta(seconds=self.stale_after_seconds)

    def _parse_timestamp(self, value: Any) -> datetime:
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        return datetime.utcnow()
