import asyncio
import logging
import time
from typing import Awaitable, Callable

from ..audio.transforms import pcm_rms, pcm_to_wav_base64
from ..glossary.models import Glossary
from ..models.schemas import TranscriptEvent
from .ollama_client import OllamaOpenAICompatClient
from .prompts import build_messages

logger = logging.getLogger(__name__)


class InferencePipeline:
    def __init__(
        self,
        client: OllamaOpenAICompatClient,
        sample_rate: int,
        glossary_inline_threshold: int,
        inference_timeout: float,
        on_result: Callable[[TranscriptEvent], Awaitable[None]],
        silence_rms_threshold: float = 0.0,
    ):
        self._client = client
        self._sample_rate = sample_rate
        self._glossary_threshold = glossary_inline_threshold
        self._timeout = inference_timeout
        self._on_result = on_result
        self._silence_rms_threshold = silence_rms_threshold

    async def run(self, queue: asyncio.Queue, glossary: Glossary | None) -> None:
        """Consumer: nunca bloquea al productor. Mientras este await está
        pendiente en Ollama, el productor sigue leyendo de ffmpeg."""
        while True:
            pcm_chunk, seq, captured_at = await queue.get()
            try:
                await self._process_chunk(pcm_chunk, seq, captured_at, glossary)
            except asyncio.TimeoutError:
                logger.error("chunk #%s: timeout (%ss) esperando a Ollama", seq, self._timeout)
            except Exception:
                logger.exception("chunk #%s: fallo inesperado en inferencia", seq)
            finally:
                queue.task_done()

    async def _process_chunk(
        self, pcm_chunk: bytes, seq: int, captured_at: float, glossary: Glossary | None
    ) -> None:
        if pcm_rms(pcm_chunk) < self._silence_rms_threshold:
            # Silencio/ruido de piso: ni llamamos a Ollama — ver
            # silence_rms_threshold en app/config.py para el porqué (un
            # modelo chico puede "alucinar" texto sobre audio silencioso en
            # vez de devolver vacío, aunque el prompt se lo pida).
            logger.debug("chunk #%s: descartado por silencio (RMS bajo umbral)", seq)
            return

        t0 = time.monotonic()
        audio_b64 = pcm_to_wav_base64(pcm_chunk, sample_rate=self._sample_rate)
        messages = build_messages(glossary, self._glossary_threshold, audio_b64)
        result = await asyncio.wait_for(
            self._client.transcribe_or_translate(messages), timeout=self._timeout,
        )
        if not result.text_es.strip() and not result.text_en.strip():
            return
        now = time.time()
        await self._on_result(
            TranscriptEvent(
                seq=seq,
                lang=result.lang,
                text_es=result.text_es,
                text_en=result.text_en,
                latency_s=time.monotonic() - t0,
                # incluye el tiempo en cola (si hubo backpressure) + inferencia
                # — la demora real "de punta a punta" desde que terminaste de
                # hablar hasta que el texto está listo.
                audio_to_text_ms=max(0, round((now - captured_at) * 1000)),
                ts=now,
            )
        )
