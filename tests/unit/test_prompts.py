from app.glossary.models import Glossary, GlossaryEntry
from app.inference.prompts import build_messages, build_system_instructions


def _glossary(n_entries: int, core_terms: set[str] | None = None) -> Glossary:
    core_terms = core_terms or set()
    return Glossary(
        talk_title="Charla de prueba",
        speakers=["Speaker Uno"],
        entries=[
            GlossaryEntry(term=f"term-{i}", core=f"term-{i}" in core_terms)
            for i in range(n_entries)
        ],
    )


def test_build_messages_shape():
    messages = build_messages(None, inline_threshold=40, audio_b64="QUJD", audio_format="wav")

    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(build_system_instructions("es"))

    user_content = messages[1]["content"]
    assert messages[1]["role"] == "user"
    assert user_content[0] == {"type": "text", "text": "Transcribí/traducí este fragmento siguiendo las reglas anteriores."}
    assert user_content[1] == {"type": "input_audio", "input_audio": {"data": "QUJD", "format": "wav"}}


def test_no_glossary_block_when_glossary_is_none():
    messages = build_messages(None, inline_threshold=40, audio_b64="QUJD")
    assert messages[0]["content"] == build_system_instructions("es")


def test_target_lang_is_injected_into_system_instructions():
    messages_es = build_messages(None, inline_threshold=40, audio_b64="QUJD", target_lang="es")
    messages_en = build_messages(None, inline_threshold=40, audio_b64="QUJD", target_lang="en")

    assert "español" in messages_es[0]["content"]
    assert "inglés" in messages_en[0]["content"]
    assert messages_es[0]["content"] != messages_en[0]["content"]


def test_small_glossary_is_included_in_full():
    glossary = _glossary(5)
    messages = build_messages(glossary, inline_threshold=40, audio_b64="QUJD")
    system_content = messages[0]["content"]

    assert glossary.talk_title in system_content
    for entry in glossary.entries:
        assert entry.term in system_content


def test_large_glossary_is_filtered_to_core_terms():
    core = {"term-0", "term-5", "term-10"}
    glossary = _glossary(50, core_terms=core)
    messages = build_messages(glossary, inline_threshold=40, audio_b64="QUJD")
    system_content = messages[0]["content"]

    for term in core:
        assert term in system_content
    # un término no-core de un glosario grande no debe aparecer
    assert "term-2" not in system_content
