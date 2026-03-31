from unittest.mock import patch

from src.game_plugins.league_shared.live_client import LeagueLiveClient
from src.game_plugins.lol.source import LolLiveDataSource
from src.game_plugins.tft.source import TftLiveDataSource


def test_live_client_is_available_when_port_open():
    with patch.object(LeagueLiveClient, "_api_port_open", return_value=True), patch.object(
        LeagueLiveClient, "_game_window_exists", return_value=False
    ):
        assert LeagueLiveClient().is_available() is True


def test_live_client_is_available_when_window_exists():
    with patch.object(LeagueLiveClient, "_api_port_open", return_value=False), patch.object(
        LeagueLiveClient, "_game_window_exists", return_value=True
    ):
        assert LeagueLiveClient().is_available() is True


def test_live_client_is_not_available_without_port_or_window():
    with patch.object(LeagueLiveClient, "_api_port_open", return_value=False), patch.object(
        LeagueLiveClient, "_game_window_exists", return_value=False
    ):
        assert LeagueLiveClient().is_available() is False


def test_plugin_sources_delegate_availability_check(mocker):
    mocked = mocker.patch.object(LeagueLiveClient, "is_available", return_value=True)
    assert LolLiveDataSource().is_available() is True
    assert TftLiveDataSource().is_available() is True
    assert mocked.call_count == 2
