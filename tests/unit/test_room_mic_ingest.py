"""Cubre específicamente la condición de carrera entre restart_mic_ingest()
(disparado por /ws/mic/{room_id}) y la supervisión de ingesta de una sala en
modo 'mic': el loop viejo de reintento con backoff (pensado para rtmp/srt/
file) NO debe activarse acá, o mataría un ffmpeg recién arrancado por una
sesión de grabación nueva antes de que termine de procesarla — la demo
"funcionaría" 2 segundos y se quedaría muda, sin error visible."""

import asyncio
from typing import AsyncIterator

import pytest

from app.config import Settings
from app.rooms.room import Room


class FakeMicIngest:
    def __init__(self, chunks_per_session: int, chunk_bytes: int):
        self.protocol = "mic"
        self.start_calls = 0
        self.stop_calls = 0
        self._chunks_per_session = chunks_per_session
        self._chunk_bytes = chunk_bytes

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def read_chunks(self, chunk_bytes: int) -> AsyncIterator[bytes]:
        for _ in range(self._chunks_per_session):
            yield b"\x00" * chunk_bytes
        # fin de la sesión (EOF) — simula que MediaRecorder/el WS se cerró.


def _make_mic_room() -> Room:
    settings = Settings(ingest_protocol="mic", chunk_seconds=1.0, sample_rate=16000, max_queue_size=10)
    room = Room(room_id="mic-room", settings=settings, glossary=None)
    room.ingest = FakeMicIngest(chunks_per_session=2, chunk_bytes=room._chunk_bytes)  # type: ignore[assignment]
    return room


async def test_restart_mic_ingest_does_not_trigger_extra_automatic_restart():
    room = _make_mic_room()
    task = asyncio.create_task(room._supervised_ingest_loop())

    await room.restart_mic_ingest()  # sesión de grabación 1
    await asyncio.sleep(0.05)  # deja correr _produce() hasta el EOF simulado
    assert room.status == "waiting_for_mic"

    await room.restart_mic_ingest()  # sesión de grabación 2
    await asyncio.sleep(0.05)
    assert room.status == "waiting_for_mic"

    # más tiempo que cualquier backoff que el loop viejo hubiera usado, para
    # confirmar que no hay un tercer start() espontáneo sin una sesión nueva.
    await asyncio.sleep(0.2)

    assert room.ingest.start_calls == 2  # exactamente 2 sesiones, ni una más
    task.cancel()


async def test_mic_room_status_is_waiting_for_mic_before_any_session():
    room = _make_mic_room()
    task = asyncio.create_task(room._supervised_ingest_loop())
    await asyncio.sleep(0.01)

    assert room.status == "waiting_for_mic"
    task.cancel()


async def test_restart_mic_ingest_rejects_non_mic_protocol():
    settings = Settings(ingest_protocol="rtmp")
    room = Room(room_id="not-mic", settings=settings, glossary=None)

    with pytest.raises(ValueError):
        await room.restart_mic_ingest()
