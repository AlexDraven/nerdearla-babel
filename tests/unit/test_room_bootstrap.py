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


def test_build_rooms_file_mode_prefers_per_room_audio_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "main.wav").write_bytes(b"RIFF....")
    (fixtures_dir / "sample_audio_5s.wav").write_bytes(b"RIFF....")

    settings = Settings(room_ids="main,room2", ingest_protocol="file", demo_audio_dir="fixtures")
    rooms = build_rooms(settings)

    by_id = {r.room_id: r for r in rooms}
    # "main" tiene su propio archivo -> se usa ese, no el fallback compartido.
    assert by_id["main"].settings.ingest_file_path == "fixtures/main.wav"
    # "room2" no tiene archivo propio -> cae al fallback compartido.
    assert by_id["room2"].settings.ingest_file_path == "fixtures/sample_audio_5s.wav"


def test_build_rooms_prefers_per_room_glossary_over_global(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    glossaries_dir = tmp_path / "glossaries"
    glossaries_dir.mkdir()
    (glossaries_dir / "main.yaml").write_text(
        'talk_title: "Charla de main"\nentries: []\n', encoding="utf-8"
    )
    global_glossary = tmp_path / "global.yaml"
    global_glossary.write_text('talk_title: "Charla global"\nentries: []\n', encoding="utf-8")

    settings = Settings(
        room_ids="main,room2",
        ingest_protocol="rtmp",
        glossary_dir="glossaries",
        glossary_path=str(global_glossary),
    )
    rooms = build_rooms(settings)

    by_id = {r.room_id: r for r in rooms}
    # "main" tiene glosario propio -> se usa ese en vez del global.
    assert by_id["main"].glossary is not None
    assert by_id["main"].glossary.talk_title == "Charla de main"
    # "room2" no tiene glosario propio -> cae al global.
    assert by_id["room2"].glossary is not None
    assert by_id["room2"].glossary.talk_title == "Charla global"
