from __future__ import annotations

from src.game_plugins.league_shared.live_client import LeagueLiveClient
from src.game_plugins.tft.overwolf_source import TftOverwolfSource


class TftLiveDataSource:
    def __init__(self):
        self._client = LeagueLiveClient()
        self._overwolf_source: TftOverwolfSource | None = None
        self._data_source = "riot_live_client"

    def configure(
        self,
        data_source: str = "riot_live_client",
        overwolf_enabled: bool = False,
        host: str = "127.0.0.1",
        port: int = 7799,
        stale_after_seconds: int = 5,
    ):
        self._data_source = data_source
        if overwolf_enabled or data_source in {"overwolf", "hybrid"}:
            self._overwolf_source = TftOverwolfSource(
                host=host,
                port=port,
                stale_after_seconds=stale_after_seconds,
            )

    def is_available(self) -> bool:
        if self._data_source == "overwolf":
            return self._overwolf_source is not None
        if self._data_source == "hybrid":
            return self._client.is_available() or self._overwolf_source is not None
        return self._client.is_available()

    def fetch_live_data(self) -> dict | None:
        """Merge Overwolf data (if connected) into the base Live Client data."""
        overwolf_data = self._overwolf_source.fetch_live_data() if self._overwolf_source is not None else None
        if self._data_source == "overwolf":
            return overwolf_data

        base = self._client.get_live_data()
        if self._data_source == "riot_live_client":
            return base
        if base is not None and overwolf_data is not None:
            base["_overwolf"] = overwolf_data.get("_overwolf", {})
            base["_source"] = "hybrid"
            return base
        return overwolf_data or base

    def has_seen_activity(self) -> bool:
        if self._data_source == "overwolf":
            return self._overwolf_source.has_seen_activity() if self._overwolf_source is not None else False
        if self._data_source == "hybrid":
            return self._client.last_seen_in_game or (
                self._overwolf_source.has_seen_activity() if self._overwolf_source is not None else False
            )
        return self._client.last_seen_in_game

    def overwolf_connected(self) -> bool:
        return self._overwolf_source is not None and self._overwolf_source.is_connected()
