import base64
import io
from abc import ABC, abstractmethod

import anthropic
import openai
import google.generativeai as genai
from PIL import Image


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
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)
        self._max_tokens = max_tokens
        self._temperature = temperature

    def analyze(self, image_bytes: bytes, prompt: str) -> str:
        img = Image.open(io.BytesIO(image_bytes))
        resp = self._model.generate_content(
            [prompt, img],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        return resp.text


def get_provider(name: str, cfg: dict) -> BaseProvider:
    providers = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
    }
    if name not in providers:
        raise ValueError(f"Unknown provider: {name}")
    return providers[name](
        api_key=cfg["api_key"],
        model=cfg["model"],
        max_tokens=cfg["max_tokens"],
        temperature=cfg["temperature"],
    )
