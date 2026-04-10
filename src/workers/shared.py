"""Shared utilities for worker threads."""

import datetime
import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from src.analysis_flow import AnalysisSnapshot
from src.game_plugins.base import AiPayload
from src.rule_engine import ActiveGameContext

logger = logging.getLogger("lol_coach")


class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)
    knowledge_ready = pyqtSignal(object)
    overlay_event = pyqtSignal(object)


class QaRuntimeContext:
    def __init__(self):
        self._lock = threading.Lock()
        self._active_context: ActiveGameContext | None = None
        self._rule_advice = None
        self._snapshots: list[AnalysisSnapshot] = []

    def update(
        self,
        *,
        active_context: ActiveGameContext | None,
        rule_advice,
        snapshots: list[AnalysisSnapshot],
    ) -> None:
        with self._lock:
            self._active_context = active_context
            self._rule_advice = rule_advice
            self._snapshots = list(snapshots)

    def snapshot(self) -> tuple[ActiveGameContext | None, object, list[AnalysisSnapshot]]:
        with self._lock:
            return self._active_context, self._rule_advice, list(self._snapshots)


def log_with_timestamp(tag: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    logger.info("[%s] [%s] %s", ts, tag, message)


def empty_ai_payload() -> AiPayload:
    return AiPayload(
        game_summary="",
        address=None,
        metrics={
            "game_time": "?",
            "gold": "?",
            "hp_pct": "?",
            "mana_pct": "?",
            "level": "?",
            "kda": "?",
            "cs": "?",
            "event_signature": "none",
        },
    )
