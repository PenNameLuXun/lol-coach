import pytest
from unittest.mock import MagicMock, patch, call
from src.tts_engine import WindowsTTS, EdgeTTS, OpenAITTS, get_tts_engine


def test_windows_tts_calls_say_and_runAndWait():
    with patch("src.tts_engine.pyttsx3.init") as mock_init:
        engine = MagicMock()
        mock_init.return_value = engine
        tts = WindowsTTS(rate=180, volume=1.0)
        tts.speak("push mid")
        engine.say.assert_called_once_with("push mid")
        engine.runAndWait.assert_called_once()


def test_windows_tts_stop_called_on_interrupt():
    with patch("src.tts_engine.pyttsx3.init") as mock_init:
        engine = MagicMock()
        mock_init.return_value = engine
        tts = WindowsTTS(rate=180, volume=1.0)
        tts.interrupt()
        engine.stop.assert_called_once()


def test_edge_tts_speak_calls_asyncio_run():
    with patch("src.tts_engine.asyncio.run") as mock_run:
        with patch("src.tts_engine.subprocess.run"):
            tts = EdgeTTS(voice="zh-CN-XiaoxiaoNeural")
            tts.speak("ward river")
            assert mock_run.called


def test_openai_tts_streams_audio():
    with patch("src.tts_engine.openai.OpenAI") as MockClient:
        mock_response = MagicMock()
        MockClient.return_value.audio.speech.create.return_value = mock_response
        with patch("src.tts_engine.subprocess.run"):
            tts = OpenAITTS(api_key="k", voice="alloy", model="tts-1")
            tts.speak("recall now")
            MockClient.return_value.audio.speech.create.assert_called_once()


def test_get_tts_engine_windows():
    with patch("src.tts_engine.pyttsx3.init"):
        engine = get_tts_engine("windows", {"rate": 180, "volume": 1.0})
        assert isinstance(engine, WindowsTTS)


def test_get_tts_engine_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown TTS backend"):
        get_tts_engine("unknown_tts", {})
