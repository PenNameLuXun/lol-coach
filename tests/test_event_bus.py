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
