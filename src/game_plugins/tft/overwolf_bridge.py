"""
Overwolf TFT Game Events Bridge — Python side.

Architecture:
  Overwolf App (JS) ──WebSocket──> OverwolfBridgeServer (Python, ws://127.0.0.1:7799)
                                         │
                                   OverwolfBridgeClient.get_latest_data()
                                         │
                                   TftLiveDataSource (with overwolf enabled)

The Overwolf App connects to this server and pushes TFT game state as JSON.
The Python side just keeps the latest snapshot and exposes it for polling.

Message format sent by the Overwolf App:
{
  "type": "tft_state",       // or "tft_event"
  "data": {
    "gold": 30,
    "hp": 72,
    "level": 6,
    "xp": { "current": 4, "needed": 6 },
    "alive_players": 5,
    "round": "3-2",
    "shop": ["Jinx", "Lulu", "Vi", "", "Zed"],
    "board": [
      { "name": "Jinx", "star": 2, "items": ["Rageblade"], "position": { "x": 1, "y": 0 } }
    ],
    "bench": [
      { "name": "Lulu", "star": 1, "items": [] }
    ],
    "traits": [
      { "name": "Marksman", "count": 2, "tier": 1 }
    ]
  }
}
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_BRIDGE_AVAILABLE = False
try:
    import websockets  # type: ignore
    import asyncio
    _BRIDGE_AVAILABLE = True
except ImportError:
    pass


class OverwolfBridgeServer:
    """WebSocket server that receives TFT data pushed from the Overwolf App."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7799):
        self._host = host
        self._port = port
        self._latest: dict | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: Any = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_latest(self) -> dict | None:
        with self._lock:
            return self._latest

    def start(self):
        if not _BRIDGE_AVAILABLE:
            logger.warning("[OverwolfBridge] websockets package not installed, bridge disabled. Run: pip install websockets")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="overwolf-bridge")
        self._thread.start()
        logger.info(f"[OverwolfBridge] server starting on ws://{self._host}:{self._port}")

    def stop(self):
        self._stop_event.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error(f"[OverwolfBridge] server error: {e}")
        finally:
            self._loop.close()

    async def _serve(self):
        import websockets
        async with websockets.serve(self._handler, self._host, self._port):
            logger.info(f"[OverwolfBridge] listening on ws://{self._host}:{self._port}")
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)

    async def _handler(self, websocket):
        self._connected = True
        logger.info("[OverwolfBridge] Overwolf App connected")
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                    if msg.get("type") in ("tft_state", "tft_event"):
                        with self._lock:
                            self._latest = msg.get("data", {})
                except json.JSONDecodeError:
                    logger.warning(f"[OverwolfBridge] invalid JSON: {raw[:80]}")
        except Exception:
            pass
        finally:
            self._connected = False
            logger.info("[OverwolfBridge] Overwolf App disconnected")


# Singleton instance, started on demand
_server: OverwolfBridgeServer | None = None


def get_bridge_server(host: str = "127.0.0.1", port: int = 7799) -> OverwolfBridgeServer:
    global _server
    if _server is None:
        _server = OverwolfBridgeServer(host=host, port=port)
    return _server
