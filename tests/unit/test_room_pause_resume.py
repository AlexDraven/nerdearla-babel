"""Cubre pause()/resume() de una sala no-mic: a diferencia de una
desconexión real, un pause() no debe disparar el reintento automático por
backoff de _supervised_ingest_loop (pensado para rtmp/srt/file) — si lo
hiciera, la sala "pausada" se reconectaría sola en <=30s sin que nadie lo
pidiera."""

import asyncio
from typing import AsyncIterator

import pytest

from app.config import Settings
from app.rooms.room import Room


class FakeFileIngest:
    """Simula ffmpeg en modo file/rtmp: produce chunks sin parar hasta que
    stop() lo corta (como pasaría con el stdout real al matar el proceso)."""

    def __init__(self, chunk_bytes: int):
        self.protocol = "rtmp"
        self.start_calls = 0
        self.stop_calls = 0
        self._chunk_bytes = chunk_bytes
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self.start_calls += 1
        self._stopped.clear()

    async def stop(self) -> None:
        self.stop_calls += 1
        self._stopped.set()

    async def read_chunks(self, chunk_bytes: int) -> AsyncIterator[bytes]:
        while not self._stopped.is_set():
            yield b"\x00" * chunk_bytes
            await asyncio.sleep(0.01)


def _make_room() -> Room:
    settings = Settings(ingest_protocol="rtmp", chunk_seconds=1.0, sample_rate=16000, max_queue_size=10)
    room = Room(room_id="room1", settings=settings, glossary=None)
    room.ingest = FakeFileIngest(chunk_bytes=room._chunk_bytes)  # type: ignore[assignment]
    return room


def _start_loop(room: Room) -> None:
    """Arranca _supervised_ingest_loop() como task Y la registra en
    room._ingest_task — pause()/resume() la necesitan ahí para poder
    cancelarla/reemplazarla (a diferencia de test_room_mic_ingest.py, que no
    necesita esto porque el loop de mic no se cancela nunca desde afuera)."""
    task = asyncio.create_task(room._supervised_ingest_loop())
    room._ingest_task = task
    room._tasks.append(task)


async def test_pause_stops_ingest_and_sets_status_paused():
    room = _make_room()
    _start_loop(room)
    await asyncio.sleep(0.03)
    assert room.status == "connected"

    await room.pause()

    assert room.status == "paused"
    assert room.ingest.stop_calls == 1


async def test_pause_does_not_trigger_automatic_reconnect():
    room = _make_room()
    _start_loop(room)
    await asyncio.sleep(0.03)

    await room.pause()
    # más tiempo del que tardaría cualquier backoff/reintento espontáneo.
    await asyncio.sleep(0.2)

    assert room.status == "paused"
    assert room.ingest.start_calls == 1  # ni un solo restart automático


async def test_resume_restarts_ingest():
    room = _make_room()
    _start_loop(room)
    await asyncio.sleep(0.03)
    await room.pause()

    await room.resume()
    await asyncio.sleep(0.03)

    assert room.status == "connected"
    assert room.ingest.start_calls == 2  # sesión original + la de resume()
    room._ingest_task.cancel()


async def test_pause_rejects_mic_protocol():
    settings = Settings(ingest_protocol="mic")
    room = Room(room_id="mic", settings=settings, glossary=None)

    with pytest.raises(ValueError):
        await room.pause()


async def test_resume_rejects_mic_protocol():
    settings = Settings(ingest_protocol="mic")
    room = Room(room_id="mic", settings=settings, glossary=None)

    with pytest.raises(ValueError):
        await room.resume()


async def test_non_mic_room_starts_paused_and_does_not_ingest_until_resumed():
    """Las salas no-mic (main/room2) arrancan PAUSADAS por defecto — activarlas
    es una decisión explícita desde el control room (resume()), no algo que
    pase solo con levantar el stack."""
    room = _make_room()

    await room.start()
    await asyncio.sleep(0.03)

    assert room.status == "paused"
    assert room.ingest.start_calls == 0  # nunca se arrancó el ffmpeg

    await room.resume()
    await asyncio.sleep(0.03)

    assert room.status == "connected"
    assert room.ingest.start_calls == 1

    await room.stop()


async def test_mic_room_still_starts_waiting_for_mic():
    settings = Settings(ingest_protocol="mic")
    room = Room(room_id="mic", settings=settings, glossary=None)

    await room.start()
    await asyncio.sleep(0.01)

    assert room.status == "waiting_for_mic"
    await room.stop()
