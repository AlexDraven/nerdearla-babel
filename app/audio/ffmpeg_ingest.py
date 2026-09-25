import asyncio
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class FFmpegIngest:
    """Administra el subprocess de FFmpeg que actúa como servidor RTMP/SRT
    y decodifica el stream entrante a PCM s16le 16kHz mono en stdout.
    """

    def __init__(
        self,
        protocol: str,
        host: str,
        port: int,
        sample_rate: int = 16000,
        file_path: str | None = None,
        loop: bool = True,
    ):
        self.protocol = protocol
        self.host = host
        self.port = port
        self.sample_rate = sample_rate
        self.file_path = file_path
        self.loop = loop
        self._proc: asyncio.subprocess.Process | None = None

    def _build_cmd(self) -> list[str]:
        if self.protocol == "rtmp":
            input_args = ["-listen", "1", "-i", f"rtmp://{self.host}:{self.port}/live"]
        elif self.protocol == "srt":
            input_args = ["-i", f"srt://{self.host}:{self.port}?mode=listener"]
        elif self.protocol == "file":
            if not self.file_path:
                raise ValueError("ingest_file_path es requerido para protocol='file'")
            # -re: lee el archivo a velocidad real, simulando un stream en vivo.
            # -stream_loop -1: repite el archivo indefinidamente (demo sin intervención manual).
            loop_args = ["-stream_loop", "-1"] if self.loop else []
            input_args = ["-re", *loop_args, "-i", self.file_path]
        else:
            raise ValueError(f"Protocolo de ingesta no soportado: {self.protocol}")

        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            *input_args,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate), "-ac", "1",
            "-f", "s16le", "pipe:1",
        ]

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            # Defensivo: si por algún motivo start() se llama con un proceso
            # previo todavía vivo, lo cerramos primero en vez de perder la
            # referencia y dejarlo huérfano.
            await self.stop()
        cmd = self._build_cmd()
        logger.info("Arrancando ffmpeg: %s", " ".join(cmd))
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        async for line in self._proc.stderr:
            logger.debug("[ffmpeg] %s", line.decode(errors="ignore").rstrip())

    async def read_chunks(self, chunk_bytes: int) -> AsyncIterator[bytes]:
        """Yield de bloques PCM de tamaño exacto, sin bloquear el event loop."""
        assert self._proc and self._proc.stdout
        while True:
            try:
                data = await self._proc.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    yield exc.partial
                logger.warning("ffmpeg stdout cerrado (EOF) - stream perdido")
                return
            yield data

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
