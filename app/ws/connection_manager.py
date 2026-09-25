import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Registro de viewers WS de una sala y broadcast de eventos a todos."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            connections = list(self._connections)
        if not connections:
            return

        results = await asyncio.gather(
            *(ws.send_json(payload) for ws in connections), return_exceptions=True
        )
        dead = [ws for ws, result in zip(connections, results) if isinstance(result, Exception)]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
            logger.debug("Removí %d conexión(es) muerta(s) del broadcast", len(dead))
