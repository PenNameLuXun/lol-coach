from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class OverwolfSnapshot:
    game_id: str
    data: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "overwolf"


@dataclass(slots=True)
class OverwolfEvent:
    game_id: str
    event: str
    data: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "overwolf"
