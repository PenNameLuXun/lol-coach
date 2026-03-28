import time
import queue
import pytest
from unittest.mock import MagicMock, patch
from src.capturer import Capturer


@pytest.fixture
def mock_mss():
    """Patch mss to return a fake screenshot."""
    with patch("src.capturer.mss.mss") as mock:
        fake_shot = MagicMock()
        fake_shot.rgb = b"\xff\x00\x00" * (1920 * 1080)
        fake_shot.size = (1920, 1080)
        mock.return_value.__enter__.return_value.grab.return_value = fake_shot
        yield mock


def test_capture_once_puts_bytes_in_queue(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=0, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.capture_once()
    assert not q.empty()
    data = q.get_nowait()
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_timer_captures_after_interval(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=1, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.start()
    time.sleep(1.6)
    cap.stop()
    assert not q.empty()


def test_stop_prevents_further_capture(mock_mss):
    q: queue.Queue[bytes] = queue.Queue()
    cap = Capturer(capture_queue=q, interval=1, hotkey="", region="fullscreen", jpeg_quality=50)
    cap.start()
    time.sleep(0.2)
    cap.stop()
    q.queue.clear()
    time.sleep(1.5)
    assert q.empty()


def test_jpeg_quality_affects_size(mock_mss):
    q_high: queue.Queue[bytes] = queue.Queue()
    q_low: queue.Queue[bytes] = queue.Queue()
    cap_high = Capturer(capture_queue=q_high, interval=0, hotkey="", region="fullscreen", jpeg_quality=95)
    cap_low = Capturer(capture_queue=q_low, interval=0, hotkey="", region="fullscreen", jpeg_quality=10)
    cap_high.capture_once()
    cap_low.capture_once()
    assert len(q_high.get_nowait()) > len(q_low.get_nowait())
