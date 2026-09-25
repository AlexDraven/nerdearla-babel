import logging
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from .config import get_settings
from .glossary.loader import load_glossary_from_yaml, resolve_within
from .models.schemas import RoomStatusEvent
from .rooms.bootstrap import build_rooms
from .rooms.room_manager import RoomManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("babel")

room_manager = RoomManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    rooms = build_rooms(settings)
    for room in rooms:
        room_manager.register(room)
        await room.start()
        if room.settings.ingest_protocol == "mic":
            source = "esperando a que alguien grabe por /ws/mic/{id}"
        elif room.settings.ingest_protocol == "file":
            source = f"{room.ingest.file_path} (PAUSADA — activar con POST /rooms/{room.room_id}/resume o desde el control room)"
        else:
            source = f"{room.settings.ingest_host}:{room.settings.ingest_port} (PAUSADA — activar con POST /rooms/{room.room_id}/resume o desde el control room)"
        logger.info("Sala '%s' iniciada (%s -> %s)", room.room_id, room.settings.ingest_protocol, source)

    yield

    for room in room_manager.list():
        await room.stop()


app = FastAPI(title="nerdearla-babel", lifespan=lifespan)

# El overlay y el dashboard son páginas estáticas que se abren directo desde
# el filesystem (file://) o desde otro puerto — necesitan CORS habilitado
# para poder hacer fetch()/WS contra este backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/rooms")
async def list_rooms():
    """Control room: lista todas las salas activas con su estado — prueba
    que hay >=2 sesiones corriendo en simultáneo (ver frontend/dashboard/)."""
    return [
        {
            "room_id": room.room_id,
            "status": room.status,
            "queue_size": room.queue.qsize(),
            "protocol": room.ingest.protocol,
        }
        for room in room_manager.list()
    ]


@app.get("/rooms/{room_id}/status")
async def room_status(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    return {
        "room_id": room.room_id,
        "status": room.status,
        "queue_size": room.queue.qsize(),
    }


@app.get("/rooms/{room_id}/transcript")
async def get_transcript(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    return {"room_id": room.room_id, "events": [event.model_dump() for event in room.transcript]}


@app.get("/rooms/{room_id}/transcript.txt", response_class=PlainTextResponse)
async def get_transcript_txt(room_id: str):
    """Transcript plano y descargable: sirve tanto para accesibilidad
    (alguien que no pudo seguir la charla en vivo) como para publicar el
    contenido de la charla después."""
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    return room.transcript_as_text()


@app.get("/rooms/{room_id}/glossary")
async def get_glossary(room_id: str):
    """Solo lectura: expone el glosario técnico que está usando la sala, para
    poder verificar que el mecanismo anti-alucinaciones está realmente activo."""
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    if room.glossary is None:
        return {"room_id": room.room_id, "glossary": None}
    return {"room_id": room.room_id, "glossary": room.glossary.model_dump()}


@app.post("/rooms/{room_id}/glossary")
async def reload_glossary(room_id: str, path: str):
    """Control-plane: permite cambiar el glosario de la charla en vivo sin
    reiniciar el contenedor (ej. entre charla y charla del mismo evento).

    `path` es el nombre de archivo DENTRO de `settings.glossary_dir` (no una
    ruta arbitraria del filesystem) — este endpoint es de red/sin auth, así
    que se resuelve con whitelist de directorio para evitar path traversal.
    """
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")

    settings = get_settings()
    try:
        safe_path = resolve_within(settings.glossary_dir, path)
        glossary = load_glossary_from_yaml(safe_path)
    except ValueError as exc:
        raise HTTPException(400, f"path de glosario inválido: {exc}") from exc
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise HTTPException(400, f"no se pudo cargar el glosario: {exc}") from exc

    room.glossary = glossary
    return {"ok": True, "terms": len(room.glossary.entries)}


@app.post("/rooms/{room_id}/pause")
async def pause_room(room_id: str):
    """Corta la ingesta de una sala no-mic desde el control room (ej. para
    liberarle capacidad de inferencia a la sala mic mientras alguien prueba
    con su micrófono), sin bajar el proceso ni el resto de las salas."""
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    try:
        await room.pause()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": room.status}


@app.post("/rooms/{room_id}/resume")
async def resume_room(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    try:
        await room.resume()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": room.status}


@app.websocket("/ws/room/{room_id}")
async def viewer_ws(websocket: WebSocket, room_id: str):
    """Canal de salida: clientes (overlay de subtítulos) reciben
    TranscriptEvent / RoomStatusEvent por broadcast."""
    room = room_manager.get(room_id)
    if room is None:
        await websocket.close(code=4404)
        return
    await room.connections.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # no se espera input; mantiene viva la conexión
    except WebSocketDisconnect:
        pass
    finally:
        await room.connections.disconnect(websocket)


@app.websocket("/ws/mic/{room_id}")
async def mic_ingest_ws(websocket: WebSocket, room_id: str):
    """Canal de ENTRADA: recibe frames binarios WebM/Opus desde el navegador
    de quien esté grabando (MediaRecorder, ver frontend/mic/) y los empuja
    al ffmpeg de esa sala. Rechaza si la sala no existe o no está en modo
    'mic', para no corromper por error el ffmpeg de una sala file/rtmp/srt."""
    room = room_manager.get(room_id)
    if room is None or room.ingest.protocol != "mic":
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await room.restart_mic_ingest()
    try:
        while True:
            data = await websocket.receive_bytes()
            await room.ingest.write(data)
    except WebSocketDisconnect:
        pass
    finally:
        await room.ingest.stop()
        room.status = "waiting_for_mic"
        await room.connections.broadcast(RoomStatusEvent(status="waiting_for_mic").model_dump())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
