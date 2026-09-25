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
        elif self.protocol == "mic":
            # El navegador (MediaRecorder) empuja WebM/Opus por un WebSocket
            # de ingesta (ver /ws/mic/{room_id} en app/main.py), que lo vuelca
            # a nuestro stdin. -f webm evita el autodetect — no hace falta
            # para que funcione (Matroska/WebM soporta streaming nativamente
            # y, al ser audio-only con Opus, no hay dependencia de keyframes
            # como sí la habría con video), pero evita cualquier ambigüedad.
            input_args = ["-f", "webm", "-i", "pipe:0"]
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
        stdin = asyncio.subprocess.PIPE if self.protocol == "mic" else None
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=stdin, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        asyncio.create_task(self._drain_stderr())

    async def write(self, data: bytes) -> None:
        """Escribe bytes al stdin de ffmpeg (protocol='mic'). No lanza si el
        proceso ya murió o el pipe está roto — el WS de ingesta no se tiene
        que caer por un problema transitorio de ffmpeg; el frame se descarta
        y la próxima sesión de grabación (restart_mic_ingest) lo resuelve."""
        if not self._proc or not self._proc.stdin or self._proc.returncode is not None:
            return
        try:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            logger.warning("[ffmpeg mic] pipe de stdin roto al escribir")

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
