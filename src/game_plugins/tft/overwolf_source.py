from __future__ import annotations

from src.overwolf_bridge import get_bridge_server


class TftOverwolfSource:
    def __init__(self, host: str = "127.0.0.1", port: int = 7799, stale_after_seconds: int = 5):
        self._server = get_bridge_server(host=host, port=port, stale_after_seconds=stale_after_seconds)
        self._server.start()

    def is_available(self) -> bool:
        return True

    def fetch_live_data(self) -> dict | None:
        snapshot = self._server.latest_snapshot("tft")
        if snapshot is None:
            return None
        return {
            "_game_type": "tft",
            "_source": "overwolf",
            "_overwolf": snapshot,
        }

    def has_seen_activity(self) -> bool:
        return self._server.is_game_connected("tft")

    def is_connected(self) -> bool:
        return self._server.is_game_connected("tft")
