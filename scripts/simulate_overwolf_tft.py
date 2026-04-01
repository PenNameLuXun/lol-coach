from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def post_json(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        print(f"{url} -> {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously push sample TFT snapshots into the local Overwolf bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7799)
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between pushes.")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    print(f"Sending TFT snapshots to {base} every {args.interval:.1f}s. Press Ctrl+C to stop.")

    tick = 0
    try:
        while True:
            tick += 1
            game_time_seconds = 1100 + tick
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            snapshot = {
                "source": "overwolf-sim",
                "game_id": "tft",
                "timestamp": now,
                "data": {
                    "mode": "TFT",
                    "game_time": f"{game_time_seconds // 60}:{game_time_seconds % 60:02d}",
                    "game_time_seconds": game_time_seconds,
                    "hp": 72,
                    "gold": 34 + (tick % 3),
                    "level": 7,
                    "alive_players": 5,
                    "round": "4-2",
                    "event_signature": "heartbeat",
                    "me": {
                        "name": "TestPlayer",
                    },
                    "shop": [
                        {"name": "安妮", "cost": 2},
                        {"name": "妮蔻", "cost": 3},
                        {"name": "盖伦", "cost": 1},
                        {"name": "卡尔玛", "cost": 4},
                        {"name": "慎", "cost": 2},
                    ],
                    "traits": [
                        {"name": "法师", "tier_current": 3},
                        {"name": "堡垒卫士", "tier_current": 2},
                    ],
                    "board": [],
                    "bench": [],
                },
            }
            event = {
                "source": "overwolf-sim",
                "game_id": "tft",
                "event": "heartbeat",
                "timestamp": now,
                "data": {
                    "round": "4-2",
                    "tick": tick,
                },
            }

            post_json(f"{base}/snapshot", snapshot)
            if tick == 1 or tick % 10 == 0:
                post_json(f"{base}/event", event)
                with urllib.request.urlopen(f"{base}/health", timeout=3) as response:
                    print(response.read().decode("utf-8"))

            time.sleep(max(0.2, args.interval))
    except urllib.error.URLError as exc:
        print(f"Failed to connect to Overwolf bridge at {base}: {exc}")
        print("Start the bridge first by running the app with Overwolf enabled, or add a standalone bridge runner.")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nStopped TFT snapshot simulation.")


if __name__ == "__main__":
    main()
