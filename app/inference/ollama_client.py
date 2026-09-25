import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class InferenceResult(BaseModel):
    lang: str = "unknown"
    original_text: str = ""
    translated_text: str = ""


class OllamaOpenAICompatClient:
    """IMPORTANTE: usar SIEMPRE el endpoint OpenAI-compat (/v1/chat/completions)
    para audio. El endpoint nativo /api/chat de Ollama ignora silenciosamente
    el campo de audio para gemma4 — no sirve para este caso de uso.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model

    async def transcribe_or_translate(self, messages: list[dict]) -> InferenceResult:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        try:
            return InferenceResult.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError):
            logger.warning("Respuesta no-JSON del modelo, uso fallback: %r", raw)
            return InferenceResult(lang="unknown", original_text=raw.strip())
