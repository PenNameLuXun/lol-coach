import json
import urllib.request

from src.overwolf_bridge import get_bridge_server


def _post_json(url: str, payload: dict):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 202


def test_overwolf_bridge_accepts_snapshot_and_event():
    server = get_bridge_server(host="127.0.0.1", port=7801, stale_after_seconds=30)
    server.reset()
    server.start()
    _post_json(
        "http://127.0.0.1:7801/snapshot",
        {
            "game_id": "tft",
            "data": {
                "hp": 68,
                "gold": 32,
                "level": 7,
                "shop": [{"name": "盖伦", "cost": 1}],
            },
        },
    )
    _post_json(
        "http://127.0.0.1:7801/event",
        {
            "game_id": "tft",
            "event": "round_start",
            "data": {"round": "4-2"},
        },
    )

    snapshot = server.latest_snapshot("tft")
    events = server.latest_events("tft")

    assert snapshot is not None
    assert snapshot["gold"] == 32
    assert events[0]["event"] == "round_start"
    assert server.is_game_connected("tft") is True
