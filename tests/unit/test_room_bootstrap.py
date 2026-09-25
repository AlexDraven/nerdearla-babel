from app.config import Settings
from app.rooms.bootstrap import build_rooms


def test_build_rooms_creates_one_room_per_id_with_sequential_ports():
    settings = Settings(room_ids="main,room2", ingest_base_port=1935, ingest_protocol="rtmp")

    rooms = build_rooms(settings)

    assert [r.room_id for r in rooms] == ["main", "room2"]
    assert [r.settings.ingest_port for r in rooms] == [1935, 1936]
    # confirma que "al menos 2 sesiones en simultáneo" es el comportamiento
    # de fábrica: build_rooms ya devuelve 2 Room por defecto.
    default_settings = Settings()
    assert len(build_rooms(default_settings)) >= 2


def test_build_rooms_scales_with_more_ids():
    settings = Settings(room_ids="a,b,c,d", ingest_base_port=2000, ingest_protocol="rtmp")

    rooms = build_rooms(settings)

    assert [r.room_id for r in rooms] == ["a", "b", "c", "d"]
    assert [r.settings.ingest_port for r in rooms] == [2000, 2001, 2002, 2003]


def test_build_rooms_file_mode_resolves_demo_audio_fallback():
    settings = Settings(
        room_ids="main,room2",
        ingest_protocol="file",
        demo_audio_dir="tests/fixtures",
    )

    rooms = build_rooms(settings)

    for room in rooms:
        # ninguna sala tiene un tests/fixtures/<room_id>.wav propio todavía,
        # así que ambas deben caer al fixture sintético compartido.
        assert room.settings.ingest_file_path == "tests/fixtures/sample_audio_5s.wav"
