import pytest
from unittest.mock import MagicMock, patch
from src.ai_provider import ClaudeProvider, OpenAIProvider, GeminiProvider, OpenAICompatibleProvider, get_provider


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
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value.text = "recall now"

        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash", max_tokens=100, temperature=0.7)
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "recall now"


# ── OpenAICompatibleProvider ──────────────────────────────────────────────────

def test_compat_provider_analyze_returns_text():
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        choice = MagicMock()
        choice.message.content = "buy tear"
        MockClient.return_value.chat.completions.create.return_value.choices = [choice]

        provider = OpenAICompatibleProvider(
            api_key="k", model="deepseek-chat", max_tokens=100,
            temperature=0.7, base_url="https://api.deepseek.com"
        )
        result = provider.analyze(FAKE_IMAGE, PROMPT)
        assert result == "buy tear"


def test_compat_provider_passes_base_url():
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        choice = MagicMock()
        choice.message.content = "ok"
        MockClient.return_value.chat.completions.create.return_value.choices = [choice]

        OpenAICompatibleProvider(
            api_key="k", model="llava", max_tokens=100,
            temperature=0.7, base_url="http://localhost:11434/v1"
        )
        MockClient.assert_called_once_with(api_key="k", base_url="http://localhost:11434/v1")


# ── Factory ───────────────────────────────────────────────────────────────────

def test_get_provider_returns_claude():
    with patch("src.ai_provider.anthropic.Anthropic"):
        cfg = {"api_key": "k", "model": "claude-opus-4-6", "max_tokens": 100, "temperature": 0.7}
        p = get_provider("claude", cfg)
        assert isinstance(p, ClaudeProvider)


@pytest.mark.parametrize("name,expected_url", [
    ("deepseek", "https://api.deepseek.com"),
    ("qwen",     "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("zhipu",    "https://open.bigmodel.cn/api/paas/v4/"),
    ("ollama",   "http://localhost:11434/v1"),
])
def test_get_provider_returns_compat_with_default_url(name, expected_url):
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        cfg = {"api_key": "k", "model": "some-model", "max_tokens": 100, "temperature": 0.7}
        p = get_provider(name, cfg)
        assert isinstance(p, OpenAICompatibleProvider)
        MockClient.assert_called_once_with(api_key="k", base_url=expected_url)


def test_get_provider_compat_respects_custom_base_url():
    with patch("src.ai_provider.openai.OpenAI") as MockClient:
        cfg = {"api_key": "k", "model": "llava", "max_tokens": 100,
               "temperature": 0.7, "base_url": "http://myserver:11434/v1"}
        p = get_provider("ollama", cfg)
        assert isinstance(p, OpenAICompatibleProvider)
        MockClient.assert_called_once_with(api_key="k", base_url="http://myserver:11434/v1")


def test_get_provider_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("unknown_llm", {})
