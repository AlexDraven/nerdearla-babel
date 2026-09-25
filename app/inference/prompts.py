from ..glossary.models import Glossary

TARGET_LANG_LABELS = {"es": "español", "en": "inglés"}


def build_system_instructions(target_lang: str) -> str:
    label = TARGET_LANG_LABELS.get(target_lang, target_lang)
    return f"""Sos un motor de subtitulado en vivo para una conferencia de tecnología.
Vas a recibir un fragmento de audio de 3 a 5 segundos.

Reglas:
1. Detectá el idioma en el que se habla.
2. "original_text": transcripción fiel de lo dicho en su idioma original,
   corrigiendo puntuación y eliminando muletillas, sin traducir ni resumir.
3. "translated_text": la traducción de ese mismo contenido a {label} ({target_lang}).
   Si el idioma original ya es {label}, repetí el mismo texto en "translated_text"
   (no hace falta traducir).
4. Si es silencio o no es inteligible, devolvé "original_text" y "translated_text" vacíos.
5. Usá el glosario técnico provisto para escribir bien nombres propios,
   librerías y términos técnicos (aceptá spanglish común si es lo que se oye).
6. Respondé EXCLUSIVAMENTE JSON válido:
   {{"lang": "es"|"en"|"unknown", "original_text": "...", "translated_text": "..."}}
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
    target_lang: str = "es",
    audio_format: str = "wav",
) -> list[dict]:
    block = _format_glossary_block(glossary, inline_threshold) if glossary else ""
    return [
        {"role": "system", "content": build_system_instructions(target_lang) + block},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribí/traducí este fragmento siguiendo las reglas anteriores."},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
            ],
        },
    ]
