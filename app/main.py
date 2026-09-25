import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from .config import get_settings
from .glossary.loader import load_glossary_from_yaml
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
        if room.settings.ingest_protocol == "file":
            source = room.ingest.file_path
        else:
            source = f"{room.settings.ingest_host}:{room.settings.ingest_port}"
        logger.info("Sala '%s' iniciada (%s -> %s)", room.room_id, room.settings.ingest_protocol, source)

    yield

    for room in room_manager.list():
        await room.stop()


app = FastAPI(title="nerdearla-babel", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


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


@app.post("/rooms/{room_id}/glossary")
async def reload_glossary(room_id: str, path: str):
    """Control-plane: permite cambiar el glosario de la charla en vivo sin
    reiniciar el contenedor (ej. entre charla y charla del mismo evento)."""
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    room.glossary = load_glossary_from_yaml(path)
    return {"ok": True, "terms": len(room.glossary.entries)}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
