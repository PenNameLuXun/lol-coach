from __future__ import annotations

from src.overwolf_bridge.server import OverwolfBridgeServer

_SERVERS: dict[tuple[str, int, int], OverwolfBridgeServer] = {}


def get_bridge_server(
    host: str = "127.0.0.1",
    port: int = 7799,
    stale_after_seconds: int = 5,
) -> OverwolfBridgeServer:
    key = (host, int(port), int(stale_after_seconds))
    server = _SERVERS.get(key)
    if server is None:
        server = OverwolfBridgeServer(
            host=host,
            port=port,
            stale_after_seconds=stale_after_seconds,
        )
        _SERVERS[key] = server
    return server
