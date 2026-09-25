from app.config import Settings
from app.models.schemas import TranscriptEvent
from app.rooms.room import Room


def _make_room() -> Room:
    settings = Settings(ingest_protocol="rtmp")
    return Room(room_id="test-room", settings=settings, glossary=None)


async def test_emit_transcript_appends_to_history():
    room = _make_room()
    event = TranscriptEvent(
        seq=1, lang="es", text_es="hola mundo", text_en="hello world",
        latency_s=0.2, ts=1_700_000_000.0,
    )

    await room._emit_transcript(event)

    assert list(room.transcript) == [event]


async def test_transcript_as_text_always_includes_both_languages():
    room = _make_room()
    await room._emit_transcript(
        TranscriptEvent(
            seq=1, lang="en", text_es="hola mundo", text_en="hello world",
            latency_s=0.2, ts=1_700_000_000.0,
        )
    )
    await room._emit_transcript(
        TranscriptEvent(
            seq=2, lang="es", text_es="ya está en español", text_en="already in spanish",
            latency_s=0.1, ts=1_700_000_005.0,
        )
    )

    text = room.transcript_as_text()
    lines = text.splitlines()

    assert "(en)" in lines[0]
    assert "ES: hola mundo" in lines[0]
    assert "EN: hello world" in lines[1]
    assert "(es)" in lines[2]
    assert "ES: ya está en español" in lines[2]
    assert "EN: already in spanish" in lines[3]
    assert len(lines) == 4


async def test_transcript_as_text_empty_when_no_events():
    room = _make_room()

    assert room.transcript_as_text() == ""


async def test_transcript_deque_caps_memory():
    room = _make_room()
    for i in range(10):
        await room._emit_transcript(
            TranscriptEvent(seq=i, lang="es", text_es=str(i), text_en=str(i), latency_s=0.0, ts=0.0)
        )

    # confirma el cap real (5000) sin tener que generar esa cantidad de eventos
    assert room.transcript.maxlen == 5000
    assert len(room.transcript) == 10
