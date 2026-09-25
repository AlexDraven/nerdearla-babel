from ..glossary.models import Glossary

SYSTEM_INSTRUCTIONS = """Sos un motor de subtitulado en vivo para una conferencia de tecnología.
Vas a recibir un fragmento de audio de 3 a 5 segundos.

Reglas:
1. Si el audio está en español: transcribilo, corrigiendo puntuación y
   eliminando muletillas, sin traducir ni resumir.
2. Si el audio está en inglés: traducilo al español rioplatense, fiel y
   manteniendo el registro técnico.
3. Si es silencio o no es inteligible, devolvé texto vacío.
4. Usá el glosario técnico provisto para escribir bien nombres propios,
   librerías y términos técnicos (aceptá spanglish común si es lo que se oye).
5. Respondé EXCLUSIVAMENTE JSON válido: {"lang": "es"|"en"|"unknown", "text": "..."}
"""


def _format_glossary_block(glossary: Glossary, inline_threshold: int) -> str:
    if not glossary.entries:
        return ""
    entries = glossary.entries
    if len(entries) > inline_threshold:
        # TODO(fase 2): retrieval semántico contra los últimos N outputs
        # en vez de recortar solo por flag `core`.
        entries = [e for e in entries if e.core][:inline_threshold]

    lines = [f"- {e.term}" + (f" ({', '.join(e.aliases)})" if e.aliases else "") for e in entries]
    speakers = f"Speakers: {', '.join(glossary.speakers)}.\n" if glossary.speakers else ""
    return (
        f'\nCharla: "{glossary.talk_title}".\n{speakers}'
        "Glosario técnico (grafía exacta a usar):\n" + "\n".join(lines)
    )


def build_messages(
    glossary: Glossary | None,
    inline_threshold: int,
    audio_b64: str,
    audio_format: str = "wav",
) -> list[dict]:
    block = _format_glossary_block(glossary, inline_threshold) if glossary else ""
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS + block},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribí/traducí este fragmento siguiendo las reglas anteriores."},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
            ],
        },
    ]
