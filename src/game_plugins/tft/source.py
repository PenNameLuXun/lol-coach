from src.lol_client import LolClient


class TftLiveDataSource:
    def __init__(self):
        self._client = LolClient()

    def is_available(self) -> bool:
        return True

    def fetch_live_data(self) -> dict | None:
        return self._client.get_live_data()

    def has_seen_activity(self) -> bool:
        return self._client.last_seen_in_game
