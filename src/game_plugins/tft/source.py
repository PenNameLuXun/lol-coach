from __future__ import annotations

from src.game_plugins.league_shared.live_client import LeagueLiveClient


class TftLiveDataSource:
    def __init__(self):
        self._client = LeagueLiveClient()
        self._overwolf_server = None

    def enable_overwolf(self, host: str = "127.0.0.1", port: int = 7799):
        from src.game_plugins.tft.overwolf_bridge import get_bridge_server
        self._overwolf_server = get_bridge_server(host=host, port=port)
        self._overwolf_server.start()

    def is_available(self) -> bool:
        return self._client.is_available()

    def fetch_live_data(self) -> dict | None:
        """Merge Overwolf data (if connected) into the base Live Client data."""
        base = self._client.get_live_data()
        if base is None:
            return None
        if self._overwolf_server is not None and self._overwolf_server.is_connected:
            ow_data = self._overwolf_server.get_latest()
            if ow_data:
                base["_overwolf"] = ow_data
        return base

    def has_seen_activity(self) -> bool:
        return self._client.last_seen_in_game

    def overwolf_connected(self) -> bool:
        return self._overwolf_server is not None and self._overwolf_server.is_connected
