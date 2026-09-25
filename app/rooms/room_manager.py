from .room import Room


class RoomManager:
    """Registry de salas activas. En el MVP solo se registra una Room, pero
    el registro ya soporta múltiples salas (ver docs/SCALING.md, opción 1:
    multi-room en un proceso)."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    def register(self, room: Room) -> None:
        self._rooms[room.room_id] = room

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def list(self) -> list[Room]:
        return list(self._rooms.values())
