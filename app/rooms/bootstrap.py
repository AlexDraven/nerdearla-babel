from pathlib import Path

from ..config import Settings
from ..glossary.loader import load_glossary_from_yaml
from .room import Room


def _resolve_glossary_path(room_id: str, settings: Settings, allow_global_fallback: bool = True) -> str | None:
    """Convención: <glossary_dir>/<room_id>.yaml si existe; si no (y
    `allow_global_fallback`), el glosario global (BABEL_GLOSSARY_PATH)
    compartido por las salas de demo.

    Las salas en modo "mic" NUNCA deben caer al fallback global: ese
    glosario está atado a una charla puntual (ej. el de ejemplo trae
    talk_title="Kubernetes en producción..."), y meterlo en el prompt de
    alguien grabando algo random por su micrófono confunde/contamina al
    modelo — literalmente le hace "leer" el título de una charla ajena en
    vez de transcribir lo que se dijo."""
    per_room = Path(settings.glossary_dir) / f"{room_id}.yaml"
    if per_room.exists():
        return str(per_room)
    return settings.glossary_path if allow_global_fallback else None


def _resolve_demo_audio_path(room_id: str, settings: Settings) -> str:
    """Convención: <demo_audio_dir>/<room_id>.wav si existe (para que alcance
    con dejar un archivo con ese nombre para tener demo real por sala); si no,
    cae al fixture sintético incluido en el repo."""
    demo_dir = Path(settings.demo_audio_dir)
    per_room = demo_dir / f"{room_id}.wav"
    if per_room.exists():
        return str(per_room)
    return str(demo_dir / "sample_audio_5s.wav")


def build_rooms(settings: Settings) -> list[Room]:
    """Arma una Room por cada id en BABEL_ROOM_IDS (CSV), cada una con su
    propio puerto de ingesta (ingest_base_port + índice) y, en modo "file",
    su propio archivo de audio de demo. Todas comparten el mismo Ollama.

    Los ids listados en BABEL_MIC_ROOM_IDS fuerzan protocol="mic" (alguien
    grabando en vivo desde /frontend/mic/, ver /ws/mic/{room_id} en
    app/main.py) sin importar el BABEL_INGEST_PROTOCOL global — así conviven
    salas de demo pregrabada (file) con una sala de micrófono en vivo.
    """
    room_ids = [r.strip() for r in settings.room_ids.split(",") if r.strip()]
    mic_ids = {r.strip() for r in settings.mic_room_ids.split(",") if r.strip()}
    rooms: list[Room] = []
    for i, room_id in enumerate(room_ids):
        is_mic_room = room_id in mic_ids
        glossary_path = _resolve_glossary_path(room_id, settings, allow_global_fallback=not is_mic_room)
        glossary = load_glossary_from_yaml(glossary_path) if glossary_path else None

        updates: dict = {"room_id": room_id, "ingest_port": settings.ingest_base_port + i}
        if is_mic_room:
            updates["ingest_protocol"] = "mic"
        elif settings.ingest_protocol == "file":
            updates["ingest_file_path"] = _resolve_demo_audio_path(room_id, settings)
        room_settings = settings.model_copy(update=updates)

        rooms.append(Room(room_id=room_id, settings=room_settings, glossary=glossary))
    return rooms
