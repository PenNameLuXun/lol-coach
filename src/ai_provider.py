import base64
from abc import ABC, abstractmethod

import anthropic
import openai
from google import genai
from google.genai import types


class BaseProvider(ABC):
    @abstractmethod
    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        """Send image + prompt to AI; return advice string."""


class ClaudeProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return msg.content[0].text


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.choices[0].message.content


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        return resp.text


class OpenAICompatibleProvider(BaseProvider):
    """Shared implementation for OpenAI-compatible APIs (DeepSeek, Qwen, Zhipu, Ollama)."""

    def __init__(self, api_key: str, model: str, max_tokens: int,
                 temperature: float, base_url: str):
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.choices[0].message.content


# Default base URLs for OpenAI-compatible providers
_COMPAT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4/",
    "ollama":   "http://localhost:11434/v1",
}


def get_provider(name: str, cfg: dict) -> BaseProvider:
    if name in ("claude", "openai", "gemini"):
        providers = {
            "claude": ClaudeProvider,
            "openai": OpenAIProvider,
            "gemini": GeminiProvider,
        }
        return providers[name](
            api_key=cfg["api_key"],
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
        )
    if name in _COMPAT_BASE_URLS:
        base_url = cfg.get("base_url", _COMPAT_BASE_URLS[name])
        return OpenAICompatibleProvider(
            api_key=cfg["api_key"],
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            base_url=base_url,
        )
    raise ValueError(f"Unknown provider: {name}")
