import json
from types import SimpleNamespace

from app.inference.ollama_client import OllamaOpenAICompatClient


def _fake_response(content: str):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _make_client() -> OllamaOpenAICompatClient:
    return OllamaOpenAICompatClient(base_url="http://example/v1", api_key="x", model="gemma4:e2b", timeout=5.0)


async def test_transcribe_or_translate_disables_thinking_via_reasoning_effort():
    """gemma4 viene con "thinking" activado por defecto en Ollama — es la
    mayor parte del tiempo de generación para un caso de uso que nunca lo
    muestra. `think: false` (el parámetro nativo) no se respeta en el
    endpoint OpenAI-compat (el único que sirve para mandar audio);
    `reasoning_effort: "none"` sí — confirmamos que se manda siempre."""
    captured_kwargs = {}

    async def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        return _fake_response(json.dumps({"lang": "es", "text_es": "hola", "text_en": "hello"}))

    client = _make_client()
    client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

    result = await client.transcribe_or_translate([{"role": "user", "content": "hola"}])

    assert captured_kwargs.get("extra_body") == {"reasoning_effort": "none"}
    assert result.text_es == "hola"
    assert result.text_en == "hello"


async def test_transcribe_or_translate_parses_valid_json():
    async def fake_create(**kwargs):
        return _fake_response(json.dumps({"lang": "en", "text_es": "hola", "text_en": "hi"}))

    client = _make_client()
    client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

    result = await client.transcribe_or_translate([{"role": "user", "content": "hi"}])

    assert result.lang == "en"
    assert result.text_es == "hola"
    assert result.text_en == "hi"


async def test_transcribe_or_translate_falls_back_to_raw_text_on_invalid_json():
    """Aviso encontrado en la investigación: desactivar el thinking puede
    hacer que Ollama ignore response_format=json_object en algunos casos —
    confirma que el fallback ya existente sigue funcionando (no crashea,
    no devuelve vacío)."""

    async def fake_create(**kwargs):
        return _fake_response("esto no es json válido")

    client = _make_client()
    client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

    result = await client.transcribe_or_translate([{"role": "user", "content": "hola"}])

    assert result.lang == "unknown"
    assert result.text_es == "esto no es json válido"
    assert result.text_en == "esto no es json válido"


async def test_transcribe_or_translate_handles_empty_content():
    async def fake_create(**kwargs):
        return _fake_response(None)

    client = _make_client()
    client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

    result = await client.transcribe_or_translate([{"role": "user", "content": "hola"}])

    assert result.text_es == ""
    assert result.text_en == ""


async def test_transcribe_or_translate_strips_non_latin_characters():
    """Reproduce el bug real observado en vivo: el modelo devolvió una frase
    en español con caracteres tailandeses intercalados en vez de solo
    español/inglés — confirma que se filtran antes de llegar al resultado."""

    async def fake_create(**kwargs):
        return _fake_response(
            json.dumps({"lang": "es", "text_es": "se está hablando un pocoก็ตาม", "text_en": "we are speaking a bitก็ตาม"})
        )

    client = _make_client()
    client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

    result = await client.transcribe_or_translate([{"role": "user", "content": "hola"}])

    assert "ก็ตาม" not in result.text_es
    assert "ก็ตาม" not in result.text_en
    assert result.text_es == "se está hablando un poco"
    assert result.text_en == "we are speaking a bit"
