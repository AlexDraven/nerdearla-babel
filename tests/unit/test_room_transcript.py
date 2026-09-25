from app.config import Settings
from app.models.schemas import TranscriptEvent
from app.rooms.room import Room


def _make_room() -> Room:
    settings = Settings(ingest_protocol="rtmp")
    return Room(room_id="test-room", settings=settings, glossary=None)


async def test_emit_transcript_appends_to_history():
    room = _make_room()
    event = TranscriptEvent(
        seq=1, lang="es", original_text="hola mundo", translated_text="hola mundo",
        latency_s=0.2, ts=1_700_000_000.0,
    )

    await room._emit_transcript(event)

    assert list(room.transcript) == [event]


async def test_transcript_as_text_formats_original_and_translation():
    room = _make_room()
    await room._emit_transcript(
        TranscriptEvent(
            seq=1, lang="en", original_text="hello world", translated_text="hola mundo",
            latency_s=0.2, ts=1_700_000_000.0,
        )
    )
    await room._emit_transcript(
        TranscriptEvent(
            seq=2, lang="es", original_text="ya está en español", translated_text="ya está en español",
            latency_s=0.1, ts=1_700_000_005.0,
        )
    )

    text = room.transcript_as_text()
    lines = text.splitlines()

    assert "(en) hello world" in lines[0]
    assert lines[1].strip() == "-> hola mundo"
    # cuando original y traducción coinciden, no se duplica la línea
    assert "(es) ya está en español" in lines[2]
    assert len(lines) == 3


async def test_transcript_deque_caps_memory():
    room = _make_room()
    for i in range(10):
        await room._emit_transcript(
            TranscriptEvent(seq=i, lang="es", original_text=str(i), translated_text=str(i), latency_s=0.0, ts=0.0)
        )

    # confirma el cap real (5000) sin tener que generar esa cantidad de eventos
    assert room.transcript.maxlen == 5000
    assert len(room.transcript) == 10
