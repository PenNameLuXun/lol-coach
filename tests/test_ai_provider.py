import pytest
from unittest.mock import MagicMock, patch
from src.ai_provider import ClaudeProvider, OpenAIProvider, GeminiProvider, get_provider


FAKE_IMAGE = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG bytes
PROMPT = "给出对局建议"


# ── ClaudeProvider ────────────────────────────────────────────────────────────

def test_claude_analyze_returns_text():
    with patch("src.ai_provider.anthropic.Anthropic") as MockClient:
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="push top lane")]
        MockClient.return_value.messages.create.return_value = mock_msg

        provider = ClaudeProvider(api_key="k", model="claude-opus-4-6", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "push top lane"


def test_claude_passes_correct_model():
    with patch("src.ai_provider.anthropic.Anthropic") as MockClient:
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="ok")]
        MockClient.return_value.messages.create.return_value = mock_msg

        provider = ClaudeProvider(api_key="k", model="claude-opus-4-6", max_tokens=50, temperature=0.5)
        provider.analyze(FAKE_IMAGE, PROMPT)
        call_kwargs = MockClient.return_value.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 50


# ── OpenAIProvider ────────────────────────────────────────────────────────────

def test_openai_analyze_returns_text():
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        choice = MagicMock()
        choice.message.content = "ward river"
        MockClient.return_value.chat.completions.create.return_value.choices = [choice]

        provider = OpenAIProvider(api_key="k", model="gpt-4o", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "ward river"


# ── GeminiProvider ────────────────────────────────────────────────────────────

def test_gemini_analyze_returns_text():
    with patch("src.ai_provider.genai") as mock_genai:
        with patch("src.ai_provider.Image") as mock_image:
            mock_model = MagicMock()
            mock_model.generate_content.return_value.text = "recall now"
            mock_genai.GenerativeModel.return_value = mock_model

            provider = GeminiProvider(api_key="k", model="gemini-1.5-pro", max_tokens=100, temperature=0.7)
            result = provider.analyze(FAKE_IMAGE, PROMPT)
            assert result == "recall now"


# ── Factory ───────────────────────────────────────────────────────────────────

def test_get_provider_returns_claude():
    with patch("src.ai_provider.anthropic.Anthropic"):
        cfg = {"api_key": "k", "model": "claude-opus-4-6", "max_tokens": 100, "temperature": 0.7}
        p = get_provider("claude", cfg)
        assert isinstance(p, ClaudeProvider)


def test_get_provider_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("unknown_llm", {})
