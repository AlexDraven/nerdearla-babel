import asyncio
import logging
import time
from typing import Awaitable, Callable

from ..audio.transforms import pcm_to_wav_base64
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
    ):
        self._client = client
        self._sample_rate = sample_rate
        self._glossary_threshold = glossary_inline_threshold
        self._timeout = inference_timeout
        self._on_result = on_result

    async def run(self, queue: asyncio.Queue, glossary: Glossary | None) -> None:
        """Consumer: nunca bloquea al productor. Mientras este await está
        pendiente en Ollama, el productor sigue leyendo de ffmpeg."""
        while True:
            pcm_chunk, seq = await queue.get()
            try:
                await self._process_chunk(pcm_chunk, seq, glossary)
            except asyncio.TimeoutError:
                logger.error("chunk #%s: timeout (%ss) esperando a Ollama", seq, self._timeout)
            except Exception:
                logger.exception("chunk #%s: fallo inesperado en inferencia", seq)
            finally:
                queue.task_done()

    async def _process_chunk(self, pcm_chunk: bytes, seq: int, glossary: Glossary | None) -> None:
        t0 = time.monotonic()
        audio_b64 = pcm_to_wav_base64(pcm_chunk, sample_rate=self._sample_rate)
        messages = build_messages(glossary, self._glossary_threshold, audio_b64)
        result = await asyncio.wait_for(
            self._client.transcribe_or_translate(messages), timeout=self._timeout,
        )
        if not result.text.strip():
            return
        await self._on_result(
            TranscriptEvent(seq=seq, lang=result.lang, text=result.text, latency_s=time.monotonic() - t0)
        )
