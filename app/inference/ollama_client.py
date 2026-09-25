import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .sanitize import strip_non_latin_chars

logger = logging.getLogger(__name__)


class InferenceResult(BaseModel):
    lang: str = "unknown"
    text_es: str = ""
    text_en: str = ""


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
            # gemma4 viene con "thinking" (chain-of-thought) activado por
            # defecto en Ollama, y eso es la mayor parte del tiempo de
            # generación para un caso de uso que nunca lo muestra/usa. El
            # parámetro nativo `think: false` de Ollama NO se respeta en este
            # endpoint OpenAI-compat (confirmado: es el único camino para
            # mandar audio) — `reasoning_effort: "none"` sí, y es el
            # workaround documentado para justo este caso. `extra_body` en
            # vez de kwarg de primer nivel: no depende de que esta versión
            # puntual del SDK `openai` tenga `reasoning_effort` tipado.
            extra_body={"reasoning_effort": "none"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            result = InferenceResult.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError):
            logger.warning("Respuesta no-JSON del modelo, uso fallback: %r", raw)
            fallback_text = raw.strip()
            result = InferenceResult(lang="unknown", text_es=fallback_text, text_en=fallback_text)

        # Cinturón y tiradores: aunque el prompt pide explícitamente solo
        # caracteres de español/inglés, un modelo chico a veces mete texto de
        # otro alfabeto igual (ver app/inference/sanitize.py) — lo sacamos
        # acá, determinísticamente, antes de que le llegue a algún viewer.
        result.text_es = strip_non_latin_chars(result.text_es)
        result.text_en = strip_non_latin_chars(result.text_en)
        return result
