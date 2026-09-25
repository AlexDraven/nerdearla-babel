import asyncio
import logging
import time
from collections import deque
from datetime import datetime

from ..audio.ffmpeg_ingest import FFmpegIngest
from ..config import Settings
from ..glossary.models import Glossary
from ..inference.ollama_client import OllamaOpenAICompatClient
from ..inference.pipeline import InferencePipeline
from ..models.schemas import RoomStatusEvent, TranscriptEvent
from ..ws.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_EVENTS = 5000  # cap de memoria para una sala corriendo varias horas


class Room:
    """Encapsula TODO el estado de una sala: ingesta ffmpeg, cola, pipeline
    de inferencia y viewers. Escalar a N salas = instanciar N Room
    (ver docs/SCALING.md para las dos estrategias: multi-room en un proceso
    vs. N contenedores del backend, uno por sala)."""

    def __init__(self, room_id: str, settings: Settings, glossary: Glossary | None):
        if settings.ingest_protocol == "file" and not settings.ingest_file_path:
            # Falla acá, al construir la Room (arranque del proceso), en vez
            # de en cada vuelta de _supervised_ingest_loop — si no, el error
            # queda enmascarado como un reintento silencioso cada <=30s.
            raise ValueError(
                f"[{room_id}] ingest_protocol='file' requiere ingest_file_path "
                "(revisar build_rooms()/demo_audio_dir, o pasarlo explícito)"
            )

        self.room_id = room_id
        self.settings = settings
        self.glossary = glossary
        self.status = "idle"

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
        self.connections = ConnectionManager()
        self.transcript: deque[TranscriptEvent] = deque(maxlen=MAX_TRANSCRIPT_EVENTS)
        self.ingest = FFmpegIngest(
            protocol=settings.ingest_protocol,
            host=settings.ingest_host,
            port=settings.ingest_port,
            sample_rate=settings.sample_rate,
            file_path=settings.ingest_file_path,
            loop=settings.ingest_loop,
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
            target_lang=settings.target_lang,
        )
        self._tasks: list[asyncio.Task] = []
        self._chunk_bytes = int(settings.chunk_seconds * settings.sample_rate * 2)
        self._restart_count = 0
        self._mic_restart_event = asyncio.Event()

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._supervised_ingest_loop(), name=f"ingest-{self.room_id}"))
        for i in range(self.settings.concurrent_inference_workers):
            self._tasks.append(
                asyncio.create_task(self.pipeline.run(self.queue, self.glossary), name=f"worker-{self.room_id}-{i}")
            )

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("[%s] task terminó con una excepción durante el shutdown", self.room_id, exc_info=result)
        await self.ingest.stop()

    async def _emit_transcript(self, event: TranscriptEvent) -> None:
        self.transcript.append(event)
        await self.connections.broadcast(event.model_dump())

    def transcript_as_text(self) -> str:
        """Transcript plano y legible, para descarga/accesibilidad post-charla
        (ver GET /rooms/{id}/transcript.txt)."""
        lines: list[str] = []
        for event in self.transcript:
            ts_str = datetime.fromtimestamp(event.ts).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts_str}] ({event.lang}) {event.original_text}")
            if event.translated_text.strip() and event.translated_text.strip() != event.original_text.strip():
                lines.append(f"    -> {event.translated_text}")
        return "\n".join(lines) + ("\n" if lines else "")

    async def restart_mic_ingest(self) -> None:
        """Llamado por /ws/mic/{room_id} (app/main.py) al arrancar una sesión
        de grabación nueva. Arranca un ffmpeg limpio (start() ya mata
        cualquier proceso previo) y despierta a _supervised_mic_loop para
        que retome la lectura de stdout, SIN que el loop reintente por su
        cuenta — ver la nota grande en _supervised_mic_loop."""
        if self.ingest.protocol != "mic":
            raise ValueError(f"[{self.room_id}] restart_mic_ingest solo aplica a protocol='mic'")
        await self.ingest.start()
        self._mic_restart_event.set()

    async def _supervised_ingest_loop(self) -> None:
        if self.ingest.protocol == "mic":
            await self._supervised_mic_loop()
            return

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

    async def _supervised_mic_loop(self) -> None:
        """A diferencia de rtmp/srt/file, acá NO reintentamos con backoff por
        nuestra cuenta. Motivo: cada sesión de grabación del navegador manda
        un header WebM nuevo (MediaRecorder), así que reusar/reiniciar el
        ffmpeg sin que haya una sesión nueva escribiéndole (con un header
        fresco) lo dejaría esperando datos que nunca van a llegar — y peor,
        si reiniciáramos mientras el WS de ingesta SÍ está escribiendo, le
        mataríamos el proceso por debajo sin que el navegador se entere
        (la demo "funciona" 2 segundos y se queda muda, sin error visible).
        Por eso el único que llama ingest.start()/stop() acá es
        restart_mic_ingest(), disparado por /ws/mic/{room_id}."""
        self.status = "waiting_for_mic"
        while True:
            await self._mic_restart_event.wait()
            self._mic_restart_event.clear()
            try:
                self.status = "connected"
                await self.connections.broadcast(RoomStatusEvent(status="connected").model_dump())
                await self._produce()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[%s] error en ingesta de micrófono", self.room_id)

            self.status = "waiting_for_mic"
            await self.connections.broadcast(RoomStatusEvent(status="waiting_for_mic").model_dump())

    async def _produce(self) -> None:
        seq = 0
        async for pcm_chunk in self.ingest.read_chunks(self._chunk_bytes):
            seq += 1
            # Momento en que se terminó de capturar ESTE chunk de audio (no
            # cuando arrancó) — es el punto de referencia más justo para medir
            # "cuánto tardó en aparecer el texto desde que terminaste de decir
            # esto" (ver TranscriptEvent.audio_to_text_ms).
            captured_at = time.time()
            item = (pcm_chunk, seq, captured_at)
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
