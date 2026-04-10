import base64
from abc import ABC, abstractmethod
from collections.abc import Iterator

import anthropic
import httpx
import openai
from google import genai
from google.genai import types

DEFAULT_TIMEOUT = 120  # seconds


class BaseProvider(ABC):
    @abstractmethod
    def analyze(self, image_bytes: bytes | None, prompt: str) -> str:
        """Send image + prompt to AI; return advice string.
        Pass image_bytes=None to send text-only (no screenshot)."""

    def analyze_stream(self, image_bytes: bytes | None, prompt: str) -> Iterator[str]:
        text = self.analyze(image_bytes, prompt)
        if text:
            yield text


class ClaudeProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float,
                 timeout: int = DEFAULT_TIMEOUT):
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes | None, prompt: str) -> str:
        content = self._build_content(image_bytes, prompt)
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
        )
        return msg.content[0].text

    def analyze_stream(self, image_bytes: bytes | None, prompt: str) -> Iterator[str]:
        content = self._build_content(image_bytes, prompt)
        with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text

    def _build_content(self, image_bytes: bytes | None, prompt: str):
        if image_bytes is None:
            return [{"type": "text", "text": prompt}]
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": prompt},
        ]


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float,
                 timeout: int = DEFAULT_TIMEOUT):
        self._client = openai.OpenAI(
            api_key=api_key,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes | None, prompt: str) -> str:
        content = self._build_content(image_bytes, prompt)
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
        )
        return resp.choices[0].message.content

    def analyze_stream(self, image_bytes: bytes | None, prompt: str) -> Iterator[str]:
        content = self._build_content(image_bytes, prompt)
        stream = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def _build_content(self, image_bytes: bytes | None, prompt: str):
        if image_bytes is None:
            return prompt
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"
        return [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float,
                 timeout: int = DEFAULT_TIMEOUT):
        self._client = genai.Client(
            api_key=api_key,
            http_options={"timeout": timeout},
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes | None, prompt: str) -> str:
        contents = self._build_contents(image_bytes, prompt)
        resp = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        return resp.text

    def analyze_stream(self, image_bytes: bytes | None, prompt: str) -> Iterator[str]:
        contents = self._build_contents(image_bytes, prompt)
        stream = self._client.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text

    def _build_contents(self, image_bytes: bytes | None, prompt: str):
        contents = [prompt] if image_bytes is None else [
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ]
        return contents


class OpenAICompatibleProvider(BaseProvider):
    """Shared implementation for OpenAI-compatible APIs (DeepSeek, Qwen, Zhipu, Ollama)."""

    def __init__(self, api_key: str, model: str, max_tokens: int,
                 temperature: float, base_url: str, vision: bool = True,
                 timeout: int = DEFAULT_TIMEOUT):
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._vision = vision

    def analyze(self, image_bytes: bytes | None, prompt: str) -> str:
        content = self._build_content(image_bytes, prompt)
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
        )
        return resp.choices[0].message.content

    def analyze_stream(self, image_bytes: bytes | None, prompt: str) -> Iterator[str]:
        content = self._build_content(image_bytes, prompt)
        stream = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def _build_content(self, image_bytes: bytes | None, prompt: str):
        if self._vision and image_bytes is not None:
            b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64}"
            return [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ]
        return prompt


# Default base URLs for OpenAI-compatible providers
_COMPAT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4/",
    "ollama":   "http://localhost:11434/v1",
}

# Providers that do not support image input (text-only)
_TEXT_ONLY = {"deepseek"}


def get_provider(name: str, cfg: dict) -> BaseProvider:
    timeout = int(cfg.get("timeout", DEFAULT_TIMEOUT))
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
            timeout=timeout,
        )
    if name in _COMPAT_BASE_URLS:
        base_url = cfg.get("base_url", _COMPAT_BASE_URLS[name])
        return OpenAICompatibleProvider(
            api_key=cfg["api_key"],
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            base_url=base_url,
            vision=name not in _TEXT_ONLY,
            timeout=timeout,
        )
    raise ValueError(f"Unknown provider: {name}")
