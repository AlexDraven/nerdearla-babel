from ..glossary.models import Glossary

SYSTEM_INSTRUCTIONS = """Sos un motor de subtitulado en vivo para una conferencia de tecnología.
Vas a recibir un fragmento de audio de 3 a 5 segundos.

Reglas:
1. El audio SIEMPRE está en español o en inglés — no hay otro idioma posible
   en esta conferencia. Nunca asumas ni transcribas en ningún otro idioma.
2. Detectá cuál de esos dos idiomas es el que efectivamente se habló.
3. "text_es": el texto en español. Si se habló en español, es una
   transcripción fiel (corrigiendo puntuación y sacando muletillas, sin
   resumir). Si se habló en inglés, es la traducción fiel a español.
4. "text_en": el texto en inglés — simétrico a "text_es" (transcripción fiel
   si se habló en inglés, traducción fiel si se habló en español). SIEMPRE
   completá los dos campos, nunca dejes uno vacío si el otro tiene texto.
5. Si es silencio o no es inteligible, devolvé "text_es" y "text_en" vacíos.
6. Usá el glosario técnico provisto para escribir bien nombres propios,
   librerías y términos técnicos (aceptá spanglish común si es lo que se oye).
7. Escribí ÚNICAMENTE con las letras y signos de puntuación usados en español
   e inglés (alfabeto latino, tildes, ñ, ¿¡, comillas y guiones normales).
   Nunca uses caracteres de otro alfabeto o escritura (cirílico, griego,
   chino, tailandés, árabe, etc.) — si no estás seguro de una palabra puntual,
   omitila en vez de inventar caracteres de otro idioma.
8. Respondé EXCLUSIVAMENTE JSON válido:
   {"lang": "es"|"en"|"unknown", "text_es": "...", "text_en": "..."}
"""


def build_system_instructions() -> str:
    return SYSTEM_INSTRUCTIONS


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
        {"role": "system", "content": build_system_instructions() + block},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribí/traducí este fragmento siguiendo las reglas anteriores."},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
            ],
        },
    ]
