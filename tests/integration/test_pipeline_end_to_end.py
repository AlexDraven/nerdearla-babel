"""Tests de integración que ejercitan la cola/pipeline/Room con fakes en vez
de un Ollama o FFmpeg reales (esos requieren GPU/red y se validan manualmente
con `scripts/push_test_stream.sh` contra un stack docker-compose levantado).
"""

import asyncio
from typing import AsyncIterator

import pytest

from app.config import Settings
from app.inference.ollama_client import InferenceResult
from app.inference.pipeline import InferencePipeline
from app.models.schemas import TranscriptEvent
from app.rooms.room import Room


class FakeOllamaClient:
    def __init__(self, results: list[InferenceResult]):
        self._results = iter(results)

    async def transcribe_or_translate(self, messages: list[dict]) -> InferenceResult:
        return next(self._results)


async def test_pipeline_emits_transcript_event_for_nonempty_text():
    events: list[TranscriptEvent] = []

    async def on_result(event: TranscriptEvent) -> None:
        events.append(event)

    pipeline = InferencePipeline(
        client=FakeOllamaClient([InferenceResult(lang="es", text="hola mundo")]),
        sample_rate=16000,
        glossary_inline_threshold=40,
        inference_timeout=1.0,
        on_result=on_result,
    )
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put((b"\x00\x00" * 8000, 1))

    task = asyncio.create_task(pipeline.run(queue, glossary=None))
    await queue.join()
    task.cancel()

    assert len(events) == 1
    assert events[0].seq == 1
    assert events[0].lang == "es"
    assert events[0].text == "hola mundo"


async def test_pipeline_skips_empty_text():
    events: list[TranscriptEvent] = []

    async def on_result(event: TranscriptEvent) -> None:
        events.append(event)

    pipeline = InferencePipeline(
        client=FakeOllamaClient([InferenceResult(lang="unknown", text="")]),
        sample_rate=16000,
        glossary_inline_threshold=40,
        inference_timeout=1.0,
        on_result=on_result,
    )
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put((b"\x00\x00" * 8000, 1))

    task = asyncio.create_task(pipeline.run(queue, glossary=None))
    await queue.join()
    task.cancel()

    assert events == []


async def test_pipeline_survives_client_errors_and_keeps_consuming():
    events: list[TranscriptEvent] = []

    async def on_result(event: TranscriptEvent) -> None:
        events.append(event)

    class FlakyClient:
        def __init__(self):
            self._calls = 0

        async def transcribe_or_translate(self, messages: list[dict]) -> InferenceResult:
            self._calls += 1
            if self._calls == 1:
                raise RuntimeError("Ollama no responde")
            return InferenceResult(lang="es", text="segundo chunk ok")

    pipeline = InferencePipeline(
        client=FlakyClient(),
        sample_rate=16000,
        glossary_inline_threshold=40,
        inference_timeout=1.0,
        on_result=on_result,
    )
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put((b"\x00\x00" * 8000, 1))
    await queue.put((b"\x00\x00" * 8000, 2))

    task = asyncio.create_task(pipeline.run(queue, glossary=None))
    await queue.join()
    task.cancel()

    assert len(events) == 1
    assert events[0].seq == 2
    assert events[0].text == "segundo chunk ok"


async def test_room_produce_drops_oldest_chunk_when_queue_is_full():
    settings = Settings(max_queue_size=2, chunk_seconds=1.0, sample_rate=16000)
    room = Room(room_id="test-room", settings=settings, glossary=None)

    async def fake_read_chunks(chunk_bytes: int) -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"\x00" * chunk_bytes

    room.ingest.read_chunks = fake_read_chunks  # type: ignore[method-assign]

    await room._produce()

    assert room.queue.qsize() == 2
    # con maxsize=2 y 5 items producidos en drop-oldest, deben quedar los 2 últimos (#4 y #5)
    remaining_seqs = sorted(item[1] for item in room.queue._queue)  # type: ignore[attr-defined]
    assert remaining_seqs == [4, 5]
