import queue
import pytest
from unittest.mock import MagicMock
from src.event_bus import EventBus


def test_put_and_get_capture():
    bus = EventBus()
    bus.put_capture(b"img_bytes")
    assert bus.get_capture(timeout=0.1) == b"img_bytes"


def test_put_and_get_advice():
    bus = EventBus()
    bus.put_advice("attack dragon")
    assert bus.get_advice(timeout=0.1) == "attack dragon"


def test_get_capture_empty_raises():
    bus = EventBus()
    with pytest.raises(queue.Empty):
        bus.get_capture(timeout=0.05)


def test_get_advice_empty_raises():
    bus = EventBus()
    with pytest.raises(queue.Empty):
        bus.get_advice(timeout=0.05)


def test_emit_advice_calls_listeners():
    bus = EventBus()
    cb = MagicMock()
    bus.add_advice_listener(cb)
    bus.emit_advice("push mid")
    cb.assert_called_once_with("push mid")


def test_multiple_advice_listeners():
    bus = EventBus()
    cb1, cb2 = MagicMock(), MagicMock()
    bus.add_advice_listener(cb1)
    bus.add_advice_listener(cb2)
    bus.emit_advice("ward river")
    cb1.assert_called_once_with("ward river")
    cb2.assert_called_once_with("ward river")


def test_get_latest_advice_prefers_higher_priority_qa():
    bus = EventBus()
    bus.put_advice("普通建议", source="game_ai")
    bus.put_advice("问答回答", source="qa")

    assert bus.get_latest_advice(timeout=0.1) == "问答回答"


def test_get_latest_advice_dedupes_rule_events_by_key():
    bus = EventBus()
    bus.put_advice("先推线", source="rule", dedupe_key="rule:push")
    bus.put_advice("继续推线拿塔", source="rule", dedupe_key="rule:push")

    assert bus.get_latest_advice(timeout=0.1) == "继续推线拿塔"


def test_expired_game_ai_advice_is_dropped():
    bus = EventBus()
    bus.put_advice("旧建议", source="game_ai", expires_after_seconds=-1.0)
    bus.put_advice("新问答", source="qa", expires_after_seconds=30.0)

    assert bus.get_latest_advice(timeout=0.1) == "新问答"
