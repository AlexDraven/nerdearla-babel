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
    # ids sin audio propio en tests/fixtures/ (a diferencia de "main"/"room2",
    # que desde que hay audio real de demo SÍ tienen su propio <id>.wav).
    settings = Settings(
        room_ids="sala-sin-audio-propio-1,sala-sin-audio-propio-2",
        ingest_protocol="file",
        demo_audio_dir="tests/fixtures",
    )

    rooms = build_rooms(settings)

    for room in rooms:
        assert room.settings.ingest_file_path == "tests/fixtures/sample_audio_5s.wav"


def test_build_rooms_file_mode_uses_real_demo_audio_for_default_rooms():
    """main/room2 (las 2 salas por defecto) ya tienen audio de habla real en
    el repo — confirma que el bootstrap las toma en vez de caer al fallback
    sintético."""
    settings = Settings(room_ids="main,room2", ingest_protocol="file", demo_audio_dir="tests/fixtures")

    rooms = build_rooms(settings)

    by_id = {r.room_id: r for r in rooms}
    assert by_id["main"].settings.ingest_file_path == "tests/fixtures/main.wav"
    assert by_id["room2"].settings.ingest_file_path == "tests/fixtures/room2.wav"


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


def test_build_rooms_forces_mic_protocol_for_mic_room_ids():
    settings = Settings(
        room_ids="main,mic",
        ingest_protocol="file",
        mic_room_ids="mic",
        demo_audio_dir="tests/fixtures",
    )

    rooms = build_rooms(settings)

    by_id = {r.room_id: r for r in rooms}
    # "main" sigue el protocolo global (file), con su archivo de demo resuelto.
    assert by_id["main"].settings.ingest_protocol == "file"
    assert by_id["main"].settings.ingest_file_path is not None
    # "mic" ignora el protocolo global -> se fuerza a "mic", sin file_path.
    assert by_id["mic"].settings.ingest_protocol == "mic"
    assert by_id["mic"].settings.ingest_file_path is None


def test_build_rooms_default_includes_a_mic_room():
    """BABEL_ROOM_IDS por defecto incluye una sala dedicada a que alguien
    grabe con su propio micrófono, sin ninguna config extra."""
    rooms = build_rooms(Settings())

    by_id = {r.room_id: r for r in rooms}
    assert "mic" in by_id
    assert by_id["mic"].settings.ingest_protocol == "mic"


def test_build_rooms_mic_room_never_falls_back_to_global_glossary():
    """Bug real encontrado en vivo: la sala 'mic' heredaba el glosario
    global (pensado para una charla puntual, ej. "Kubernetes en
    producción...") y el modelo terminaba "leyendo" ese título en vez de
    transcribir lo que se dijo al micrófono. La sala mic NUNCA debe caer
    al fallback global — como mucho, a un glossaries/mic.yaml explícito."""
    settings = Settings(
        room_ids="main,mic",
        mic_room_ids="mic",
        ingest_protocol="file",
        demo_audio_dir="tests/fixtures",
        glossary_path="glossaries/example-charla-kubernetes.yaml",
    )

    rooms = build_rooms(settings)

    by_id = {r.room_id: r for r in rooms}
    # "main" sí hereda el glosario global (es una charla de demo real).
    assert by_id["main"].glossary is not None
    # "mic" NO, aunque haya un glosario global configurado.
    assert by_id["mic"].glossary is None


def test_build_rooms_mic_room_uses_its_own_glossary_if_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    glossaries_dir = tmp_path / "glossaries"
    glossaries_dir.mkdir()
    (glossaries_dir / "mic.yaml").write_text('talk_title: "Glosario propio de mic"\nentries: []\n', encoding="utf-8")

    settings = Settings(
        room_ids="mic",
        mic_room_ids="mic",
        glossary_dir="glossaries",
        glossary_path="glossaries/otra-charla.yaml",  # ni siquiera hace falta que exista
    )

    rooms = build_rooms(settings)

    assert rooms[0].glossary is not None
    assert rooms[0].glossary.talk_title == "Glosario propio de mic"
