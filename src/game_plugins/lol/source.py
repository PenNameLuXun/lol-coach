from src.game_plugins.league_shared.live_client import LeagueLiveClient


class LolLiveDataSource:
    def __init__(self):
        self._client = LeagueLiveClient()

    def is_available(self) -> bool:
        return self._client.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._client.get_live_data()

    def has_seen_activity(self) -> bool:
        return self._client.last_seen_in_game
