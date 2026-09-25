"""Tests de integración que ejercitan la cola/pipeline/Room con fakes en vez
de un Ollama o FFmpeg reales (esos requieren GPU/red y se validan manualmente
con `scripts/push_test_stream.sh` contra un stack docker-compose levantado).
"""

import asyncio
from typing import AsyncIterator

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
        client=FakeOllamaClient(
            [InferenceResult(lang="en", original_text="hello world", translated_text="hola mundo")]
        ),
        sample_rate=16000,
        glossary_inline_threshold=40,
        inference_timeout=1.0,
        on_result=on_result,
        target_lang="es",
    )
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put((b"\x00\x00" * 8000, 1))

    task = asyncio.create_task(pipeline.run(queue, glossary=None))
    await queue.join()
    task.cancel()

    assert len(events) == 1
    assert events[0].seq == 1
    assert events[0].lang == "en"
    assert events[0].original_text == "hello world"
    assert events[0].translated_text == "hola mundo"


async def test_pipeline_skips_empty_text():
    events: list[TranscriptEvent] = []

    async def on_result(event: TranscriptEvent) -> None:
        events.append(event)

    pipeline = InferencePipeline(
        client=FakeOllamaClient([InferenceResult(lang="unknown", original_text="", translated_text="")]),
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
            return InferenceResult(lang="es", original_text="segundo chunk ok", translated_text="segundo chunk ok")

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
    assert events[0].original_text == "segundo chunk ok"


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


async def test_two_rooms_process_concurrently_without_blocking_each_other():
    """Reproduce el requisito de la Vibeathon: al menos 2 sesiones en simultáneo.
    Dos Room con fakes lentos (uno más lento que el otro) deben terminar de
    procesar sus chunks sin que una bloquee a la otra."""
    events_a: list[TranscriptEvent] = []
    events_b: list[TranscriptEvent] = []

    async def make_pipeline(delay: float, events: list[TranscriptEvent]) -> InferencePipeline:
        class SlowClient:
            async def transcribe_or_translate(self, messages: list[dict]) -> InferenceResult:
                await asyncio.sleep(delay)
                return InferenceResult(lang="es", original_text="ok", translated_text="ok")

        async def on_result(event: TranscriptEvent) -> None:
            events.append(event)

        return InferencePipeline(
            client=SlowClient(),
            sample_rate=16000,
            glossary_inline_threshold=40,
            inference_timeout=2.0,
            on_result=on_result,
        )

    pipeline_a = await make_pipeline(0.3, events_a)
    pipeline_b = await make_pipeline(0.05, events_b)

    queue_a: asyncio.Queue = asyncio.Queue()
    queue_b: asyncio.Queue = asyncio.Queue()
    await queue_a.put((b"\x00\x00" * 8000, 1))
    await queue_b.put((b"\x00\x00" * 8000, 1))

    task_a = asyncio.create_task(pipeline_a.run(queue_a, glossary=None))
    task_b = asyncio.create_task(pipeline_b.run(queue_b, glossary=None))

    # la sala "b" (más rápida) debe completar bien antes que la "a" (más
    # lenta) siga en vuelo, demostrando que corren en paralelo y no en serie.
    await asyncio.wait_for(queue_b.join(), timeout=1.0)
    assert events_b and not events_a

    await asyncio.wait_for(queue_a.join(), timeout=1.0)
    assert events_a

    task_a.cancel()
    task_b.cancel()
