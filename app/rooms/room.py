import asyncio
import logging

from ..audio.ffmpeg_ingest import FFmpegIngest
from ..config import Settings
from ..glossary.models import Glossary
from ..inference.ollama_client import OllamaOpenAICompatClient
from ..inference.pipeline import InferencePipeline
from ..models.schemas import RoomStatusEvent, TranscriptEvent
from ..ws.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class Room:
    """Encapsula TODO el estado de una sala: ingesta ffmpeg, cola, pipeline
    de inferencia y viewers. Escalar a N salas = instanciar N Room
    (ver docs/SCALING.md para las dos estrategias: multi-room en un proceso
    vs. N contenedores del backend, uno por sala)."""

    def __init__(self, room_id: str, settings: Settings, glossary: Glossary | None):
        self.room_id = room_id
        self.settings = settings
        self.glossary = glossary
        self.status = "idle"

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
        self.connections = ConnectionManager()
        self.ingest = FFmpegIngest(
            protocol=settings.ingest_protocol,
            host=settings.ingest_host,
            port=settings.ingest_port,
            sample_rate=settings.sample_rate,
        )
        client = OllamaOpenAICompatClient(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            model=settings.ollama_model,
            timeout=settings.inference_timeout_seconds,
        )
        self.pipeline = InferencePipeline(
            client=client,
            sample_rate=settings.sample_rate,
            glossary_inline_threshold=settings.glossary_inline_threshold,
            inference_timeout=settings.inference_timeout_seconds,
            on_result=self._emit_transcript,
        )
        self._tasks: list[asyncio.Task] = []
        self._chunk_bytes = int(settings.chunk_seconds * settings.sample_rate * 2)
        self._restart_count = 0

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._supervised_ingest_loop(), name=f"ingest-{self.room_id}"))
        for i in range(self.settings.concurrent_inference_workers):
            self._tasks.append(
                asyncio.create_task(self.pipeline.run(self.queue, self.glossary), name=f"worker-{self.room_id}-{i}")
            )

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.ingest.stop()

    async def _emit_transcript(self, event: TranscriptEvent) -> None:
        await self.connections.broadcast(event.model_dump())

    async def _supervised_ingest_loop(self) -> None:
        backoff = self.settings.ffmpeg_restart_backoff_seconds
        while True:
            try:
                self.status = "connecting"
                await self.ingest.start()
                self.status = "connected"
                self._restart_count = 0
                await self.connections.broadcast(RoomStatusEvent(status="connected").model_dump())
                await self._produce()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[%s] error en ingesta ffmpeg", self.room_id)

            self.status = "disconnected"
            self._restart_count += 1
            await self.connections.broadcast(
                RoomStatusEvent(status="reconnecting", detail=f"intento {self._restart_count}").model_dump()
            )
            await asyncio.sleep(min(backoff * self._restart_count, 30))

    async def _produce(self) -> None:
        seq = 0
        async for pcm_chunk in self.ingest.read_chunks(self._chunk_bytes):
            seq += 1
            item = (pcm_chunk, seq)
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                try:
                    dropped = self.queue.get_nowait()
                    self.queue.task_done()
                    logger.warning("[%s] queue llena: descarto chunk #%s por #%s", self.room_id, dropped[1], seq)
                except asyncio.QueueEmpty:
                    pass
                self.queue.put_nowait(item)
