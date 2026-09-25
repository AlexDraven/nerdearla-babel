# PLAN.md — nerdearla-babel

Solución open source self-hosted de accesibilidad para conferencias de tecnología (Nerdearla): transcripción en vivo (ES → ES) y traducción (EN → ES), corriendo 100% en un VPS propio con GPU, pensada para escalar a múltiples salas simultáneas sin pagar por minuto de procesamiento a un SaaS externo.

Repo greenfield: este documento es el blueprint técnico para implementarlo desde cero.

> **Nota**: las secciones 1-8 documentan el diseño original (una sola sala, salida `{"lang","text"}`). La sección 9 resume cómo cambió para la Vibeathon (multi-sala real por defecto, salida dual `original_text`/`translated_text`, modo de ingesta por archivo, transcript exportable, dashboard). Los snippets de las secciones 1-8 no se reescribieron para no duplicar esfuerzo bajo presión de tiempo — **el código en `app/` es siempre la fuente de verdad**, no estos bloques de código.

## 0. Decisiones de diseño clave (resumen ejecutivo)

- **Ingesta de audio: FFmpeg como servidor RTMP/SRT** (`-listen 1` / `mode=listener`), recibiendo el push directo de OBS o de la consola de sonido de la sala. No hay WebSocket de ingesta de audio — el protocolo que ya habla OBS es RTMP/SRT, así que no tiene sentido agregar un cliente capturador intermedio en el navegador para el MVP.
- **Un solo pipeline de inferencia, no dos.** En vez de separar "transcripción ES→ES" y "traducción EN→ES" en dos flujos, se usa **un único prompt** que le pide al modelo detectar el idioma y decidir internamente si limpia/puntúa (ES) o traduce (EN), devolviendo siempre español. Más simple operacionalmente: un solo call a Ollama por chunk, un solo timeout que manejar, un solo punto de falla.
- **Backpressure = drop-oldest con cola acotada** (`asyncio.Queue(maxsize=2)`, ~8-10s de buffer). En captioning en vivo la latencia importa más que la completitud: si Ollama se atrasa, se prefiere perder un chunk intermedio antes que acumular un delay creciente que nunca se recupera.
- **Cliente OpenAI-compatible (librería `openai`) apuntando a `http://ollama:11434/v1`** para todo lo que involucre audio. **Hallazgo crítico verificado**: el endpoint nativo de Ollama `/api/chat` ignora silenciosamente el campo de audio para los modelos Gemma — no sirve para este caso de uso. La única forma real de mandar audio a `gemma4:e2b`/`gemma4:e4b` en Ollama es vía el endpoint **OpenAI-compatible** `/v1/chat/completions`, con bloques `input_audio` en base64. La librería nativa `ollama` no se usa para inferencia, solo (opcionalmente) para scripts de administración de modelos.
- **`Room` como unidad de escalado.** MVP: una sola sala por instancia del backend. Toda la lógica de una sala (FFmpeg, cola, pipeline, viewers) vive encapsulada en una clase `Room`, de forma que escalar a N salas sea instanciar N `Room` (multi-room en un proceso) o correr N contenedores del backend (recomendado en producción, ver sección 7).
- **Modelo default: `gemma4:e2b`** (liviano, baja latencia — mejor para mantener chunks de 3-5s procesándose rápido en una T4/L4 compartida entre salas), configurable a `gemma4:e4b` (mayor calidad, más lento) vía variable de entorno.

---

## 1. Estructura de directorios

```
nerdearla-babel/
├── PLAN.md
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── Makefile
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── audio/
│   │   ├── ffmpeg_ingest.py       # subprocess ffmpeg, lectura async de stdout
│   │   └── transforms.py          # PCM -> WAV -> base64
│   ├── glossary/
│   │   ├── models.py              # Glossary / GlossaryEntry (pydantic)
│   │   └── loader.py              # carga desde YAML (API a futuro)
│   ├── inference/
│   │   ├── prompts.py             # construcción de prompt + inyección de glosario
│   │   ├── ollama_client.py       # wrapper cliente OpenAI-compat
│   │   └── pipeline.py            # consumer: queue -> Ollama -> broadcast
│   ├── models/
│   │   └── schemas.py             # TranscriptEvent, RoomStatusEvent
│   ├── rooms/
│   │   ├── room.py                # unidad de escalado: 1 sala = 1 Room
│   │   └── room_manager.py        # registry de salas activas
│   └── ws/
│       └── connection_manager.py  # broadcast a N viewers
├── glossaries/
│   └── example-charla-kubernetes.yaml
├── frontend/
│   └── overlay/
│       ├── index.html             # overlay de subtítulos (OBS browser source)
│       ├── style.css
│       └── app.js                 # cliente WS con auto-reconnect
├── scripts/
│   ├── pull_model.sh
│   └── push_test_stream.sh        # ffmpeg -re -i sample.wav -f flv rtmp://...
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SCALING.md
│   └── DEPLOYMENT.md
└── tests/
    ├── unit/
    │   ├── test_prompts.py
    │   ├── test_glossary_loader.py
    │   └── test_transforms.py
    ├── integration/
    │   └── test_pipeline_end_to_end.py
    └── fixtures/
        └── sample_audio_5s.wav
```

---

## 2. Entorno y Docker

### `requirements.txt`
```
fastapi>=0.115,<0.116
uvicorn[standard]>=0.32,<0.33
websockets>=13,<14
openai>=1.50,<2
pydantic>=2.7,<3
pydantic-settings>=2.4,<3
pyyaml>=6.0,<7
httpx>=0.27,<1
python-multipart>=0.0.9
```

### `requirements-dev.txt`
```
pytest>=8.0
pytest-asyncio>=0.24
ollama>=0.3   # opcional: solo para scripts de admin (list/pull de modelos), no para inferencia
```

### `Dockerfile`
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY glossaries ./glossaries

EXPOSE 8000 1935 9998/udp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker-compose.yml`
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: babel-ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    environment:
      OLLAMA_HOST: 0.0.0.0
      OLLAMA_NUM_PARALLEL: 2
      OLLAMA_KEEP_ALIVE: 30m
      OLLAMA_MAX_LOADED_MODELS: 1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s

  # Descarga el modelo la primera vez que se levanta el stack. Corre una
  # sola vez (restart: "no") y termina; no bloquea el healthcheck de ollama.
  ollama-init:
    image: ollama/ollama:latest
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_HOST: http://ollama:11434
    entrypoint: ["/bin/sh", "-c", "ollama pull ${OLLAMA_MODEL:-gemma4:e2b}"]
    restart: "no"

  backend:
    build: .
    container_name: babel-backend
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
    ports:
      - "8000:8000"        # HTTP + WS viewers/control
      - "1935:1935"        # RTMP ingest (OBS push)
      - "9998:9998/udp"    # SRT ingest alternativo
    environment:
      BABEL_ROOM_ID: main
      BABEL_OLLAMA_BASE_URL: http://ollama:11434/v1
      BABEL_OLLAMA_MODEL: ${OLLAMA_MODEL:-gemma4:e2b}
      BABEL_INGEST_PROTOCOL: rtmp
      BABEL_INGEST_HOST: 0.0.0.0
      BABEL_INGEST_PORT: 1935
      BABEL_CHUNK_SECONDS: 4
      BABEL_MAX_QUEUE_SIZE: 2
      BABEL_GLOSSARY_PATH: /app/glossaries/example-charla-kubernetes.yaml
      BABEL_LOG_LEVEL: INFO
    volumes:
      - ./glossaries:/app/glossaries:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
      interval: 15s
      timeout: 5s
      retries: 5

volumes:
  ollama_models:
```

**Prerequisitos del host** (ver `docs/DEPLOYMENT.md`): driver NVIDIA instalado, `nvidia-container-toolkit` instalado (reiniciar Docker después), y Docker Compose v2 (soporte de `deploy.resources.reservations.devices`). Nunca usar `latest` en producción real — pinnear la versión de la imagen `ollama/ollama` una vez estabilizado el setup.

---

## 3. Flujo de datos asíncrono

```
OBS/consola  ──RTMP/SRT──▶  FFmpeg (subprocess, -listen 1)  ──PCM s16le stdout──▶
   │                                                                    │
   │                                                        readexactly(chunk_bytes)
   │                                                                    ▼
   │                                              Producer loop (Room._produce)
   │                                                                    │
   │                                              queue.put_nowait()  (maxsize=2,
   │                                              drop-oldest si está llena)
   │                                                                    ▼
   │                                                          asyncio.Queue
   │                                                                    │
   │                                          N workers (InferencePipeline.run)
   │                                                await queue.get()
   │                                                                    ▼
   │                                    PCM -> WAV -> base64  ->  build_messages(glosario)
   │                                                                    ▼
   │                                    AsyncOpenAI(base_url=ollama).chat.completions.create(
   │                                        model, messages, response_format=json_object)
   │                                                                    ▼
   │                                              InferenceResult{lang, text}
   │                                                                    ▼
Viewers ◀── WS broadcast (ConnectionManager) ◀── TranscriptEvent
```

### Por qué la ingesta nunca se bloquea

El productor (lectura de `ffmpeg.stdout`) y los consumers (llamadas a Ollama) son **tasks de asyncio separadas**. El productor solo hace `await stdout.readexactly(...)` y `queue.put_nowait(...)` (no bloqueante); nunca espera a que termine una inferencia. Si Ollama tarda 8s en un chunk de 4s, el productor sigue leyendo y llenando la cola; cuando la cola (tamaño 2) se llena, se descarta el ítem más viejo y se sigue.

### Backpressure — política explícita

- `MAX_QUEUE_SIZE` (default `2`, ~8-10s de buffer): suficiente para absorber jitter normal sin acumular latencia perceptible.
- Política **drop-oldest**: al llenarse, se hace `queue.get_nowait()` del más viejo y se encola el nuevo. Se prefiere sobre `drop-newest` (que congelaría el output) o crecer sin límite (que acumularía delay indefinido — inaceptable para subtítulos en vivo).
- `CONCURRENT_INFERENCE_WORKERS` (default `1`): subirlo permite procesar chunks en paralelo, pero debe ir en línea con `OLLAMA_NUM_PARALLEL` del lado de Ollama para no saturar la GPU (T4/L4 con `gemma4:e2b` probablemente soporta 1-2 en paralelo cómodamente).

### Gestión async del subprocess FFmpeg

- `asyncio.create_subprocess_exec(..., stdout=PIPE, stderr=PIPE)` — nunca `subprocess.Popen` (bloqueante).
- Lectura con `stdout.readexactly(chunk_bytes)` (no `read()`, que puede devolver menos bytes de los pedidos) — así cada chunk tiene tamaño exacto y previsible (`CHUNK_SECONDS * SAMPLE_RATE * 2 bytes`).
- `stderr` se drena en una task separada (`_drain_stderr`) para logging, evitando que el buffer de stderr se llene y bloquee ffmpeg.

### Manejo de errores / reconexión

| Escenario | Detección | Acción |
|---|---|---|
| OBS corta el RTMP | `readexactly` lanza `IncompleteReadError` (EOF) | `Room._supervised_ingest_loop` captura, marca sala `disconnected`, notifica a viewers (`RoomStatusEvent`), reintenta `ingest.start()` con backoff exponencial (cap 30s) |
| Ollama no responde / timeout | `asyncio.wait_for(..., timeout=INFERENCE_TIMEOUT_SECONDS)` lanza `TimeoutError` | Se loguea, se descarta el chunk (no se emite nada a viewers), el worker sigue con el próximo `queue.get()` — nunca muere |
| Ollama devuelve error HTTP / conexión rechazada | excepción del cliente `openai` | Igual que arriba: catch genérico en `pipeline.run`, log, continuar |
| Respuesta no es JSON válido | `ValidationError` / `JSONDecodeError` en `ollama_client` | Fallback: se envuelve el texto crudo como `InferenceResult(lang="unknown", text=raw)` en vez de descartar todo |
| Chunk de silencio/ruido | el propio modelo devuelve `text=""` | `pipeline` no emite evento (evita "subtítulos vacíos" parpadeando) |
| Viewer se desconecta a mitad de un broadcast | excepción en `ws.send_json` dentro de `asyncio.gather(..., return_exceptions=True)` | Se remueve del set de `ConnectionManager` sin afectar al resto |

---

## 4. Estrategia de inyección de contexto / glosario técnico

- **Carga**: un YAML por charla en `glossaries/<slug>.yaml`, apuntado por env var `BABEL_GLOSSARY_PATH` al arrancar la sala. Además se expone `POST /rooms/{room_id}/glossary?path=...` para recargarlo sin reiniciar el contenedor (cambio de charla en el mismo evento).
- **Modelo de datos** (`app/glossary/models.py`):
  ```python
  class GlossaryEntry(BaseModel):
      term: str
      aliases: list[str] = []
      note: str | None = None
      core: bool = False   # siempre se incluye, aunque el glosario sea grande

  class Glossary(BaseModel):
      talk_title: str
      speakers: list[str] = []
      entries: list[GlossaryEntry] = []
  ```
- **Eficiencia de tokens** — regla simple para el MVP (evita over-engineering prematuro):
  - Si `len(glossary.entries) <= GLOSSARY_INLINE_THRESHOLD` (default `40`): se manda el glosario completo en cada chunk. Para charlas típicas (10-40 términos) esto son unas pocas decenas de tokens, insignificante frente al costo de decodificar audio.
  - Si es más grande: se filtra a solo las entries marcadas `core: true` (curadas a mano por quien prepara el glosario — nombres de speakers, producto de la charla, 10-15 términos "calientes"), truncado a `GLOSSARY_INLINE_THRESHOLD`.
  - **Fase 2 (documentada, no implementada en el MVP)**: retrieval dinámico — mantener una ventana de los últimos N textos emitidos y hacer fuzzy-match (`rapidfuzz`) o embeddings contra el glosario completo para traer solo los términos con más probabilidad de aparecer en el próximo chunk. Se deja como `TODO` explícito en `prompts.py`.
- **Integración con el prompt único** (ES↔EN): el glosario se inyecta en el mensaje `system`, junto con las instrucciones de detección de idioma/transcripción/traducción, de modo que el modelo tenga el contexto disponible sin importar en qué idioma hable el speaker.

---

## 5. Esqueleto funcional

### `app/config.py`
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BABEL_", env_file=".env")

    room_id: str = "main"

    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_api_key: str = "ollama"          # dummy, lo exige el cliente openai
    ollama_model: str = "gemma4:e2b"        # configurable a gemma4:e4b

    ingest_protocol: str = "rtmp"           # "rtmp" | "srt"
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 1935
    sample_rate: int = 16000
    chunk_seconds: float = 4.0

    max_queue_size: int = 2
    concurrent_inference_workers: int = 1
    inference_timeout_seconds: float = 12.0
    ffmpeg_restart_backoff_seconds: float = 2.0

    glossary_path: str | None = None
    glossary_inline_threshold: int = 40

    log_level: str = "INFO"


_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

### `app/audio/ffmpeg_ingest.py`
```python
import asyncio
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class FFmpegIngest:
    """Administra el subprocess de FFmpeg que actúa como servidor RTMP/SRT
    y decodifica el stream entrante a PCM s16le 16kHz mono en stdout.
    """

    def __init__(self, protocol: str, host: str, port: int, sample_rate: int = 16000):
        self.protocol = protocol
        self.host = host
        self.port = port
        self.sample_rate = sample_rate
        self._proc: asyncio.subprocess.Process | None = None

    def _build_cmd(self) -> list[str]:
        if self.protocol == "rtmp":
            input_args = ["-listen", "1", "-i", f"rtmp://{self.host}:{self.port}/live"]
        elif self.protocol == "srt":
            input_args = ["-i", f"srt://{self.host}:{self.port}?mode=listener"]
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
```

### `app/inference/ollama_client.py`
```python
import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class InferenceResult(BaseModel):
    lang: str = "unknown"
    text: str = ""


class OllamaOpenAICompatClient:
    """IMPORTANTE: usar SIEMPRE el endpoint OpenAI-compat (/v1/chat/completions)
    para audio. El endpoint nativo /api/chat de Ollama ignora silenciosamente
    el campo de audio para gemma4 — no sirve para este caso de uso.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model

    async def transcribe_or_translate(self, messages: list[dict]) -> InferenceResult:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        try:
            return InferenceResult.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError):
            logger.warning("Respuesta no-JSON del modelo, uso fallback: %r", raw)
            return InferenceResult(lang="unknown", text=raw.strip())
```

### `app/inference/prompts.py`
```python
from ..glossary.models import Glossary

SYSTEM_INSTRUCTIONS = """Sos un motor de subtitulado en vivo para una conferencia de tecnología.
Vas a recibir un fragmento de audio de 3 a 5 segundos.

Reglas:
1. Si el audio está en español: transcribilo, corrigiendo puntuación y
   eliminando muletillas, sin traducir ni resumir.
2. Si el audio está en inglés: traducilo al español rioplatense, fiel y
   manteniendo el registro técnico.
3. Si es silencio o no es inteligible, devolvé texto vacío.
4. Usá el glosario técnico provisto para escribir bien nombres propios,
   librerías y términos técnicos (aceptá spanglish común si es lo que se oye).
5. Respondé EXCLUSIVAMENTE JSON válido: {"lang": "es"|"en"|"unknown", "text": "..."}
"""


def _format_glossary_block(glossary: Glossary, inline_threshold: int) -> str:
    if not glossary.entries:
        return ""
    entries = glossary.entries
    if len(entries) > inline_threshold:
        # TODO(fase 2): retrieval semántico contra los últimos N outputs
        # en vez de recortar solo por flag `core`.
        entries = [e for e in entries if e.core][:inline_threshold]

    lines = [f"- {e.term}" + (f" ({', '.join(e.aliases)})" if e.aliases else "") for e in entries]
    speakers = f"Speakers: {', '.join(glossary.speakers)}.\n" if glossary.speakers else ""
    return (
        f'\nCharla: "{glossary.talk_title}".\n{speakers}'
        "Glosario técnico (grafía exacta a usar):\n" + "\n".join(lines)
    )


def build_messages(glossary: Glossary | None, inline_threshold: int, audio_b64: str, audio_format: str = "wav") -> list[dict]:
    block = _format_glossary_block(glossary, inline_threshold) if glossary else ""
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS + block},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribí/traducí este fragmento siguiendo las reglas anteriores."},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
            ],
        },
    ]
```

### `app/inference/pipeline.py`
```python
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
```

### `app/rooms/room.py` (unidad de escalado)
```python
import asyncio
import logging

from ..audio.ffmpeg_ingest import FFmpegIngest
from ..config import Settings
from ..glossary.models import Glossary
from ..inference.ollama_client import OllamaOpenAICompatClient
from ..inference.pipeline import InferencePipeline
from ..models.schemas import RoomStatusEvent
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
        await self.ingest.stop()

    async def _emit_transcript(self, event) -> None:
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
```

### `app/main.py`
```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from .config import get_settings
from .glossary.loader import load_glossary_from_yaml
from .rooms.room import Room
from .rooms.room_manager import RoomManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("babel")

room_manager = RoomManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    glossary = load_glossary_from_yaml(settings.glossary_path) if settings.glossary_path else None
    if glossary:
        logger.info("Glosario cargado: %s (%d términos)", glossary.talk_title, len(glossary.entries))

    room = Room(room_id=settings.room_id, settings=settings, glossary=glossary)
    room_manager.register(room)
    await room.start()
    logger.info(
        "Sala '%s' iniciada. Esperando stream %s en %s:%s",
        room.room_id, settings.ingest_protocol, settings.ingest_host, settings.ingest_port,
    )
    yield
    await room.stop()


app = FastAPI(title="nerdearla-babel", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/rooms/{room_id}/status")
async def room_status(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    return {
        "room_id": room.room_id,
        "status": room.status,
        "queue_size": room.queue.qsize(),
    }


@app.post("/rooms/{room_id}/glossary")
async def reload_glossary(room_id: str, path: str):
    """Control-plane: permite cambiar el glosario de la charla en vivo sin
    reiniciar el contenedor (ej. entre charla y charla del mismo evento)."""
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(404, "sala no encontrada")
    room.glossary = load_glossary_from_yaml(path)
    return {"ok": True, "terms": len(room.glossary.entries)}


@app.websocket("/ws/room/{room_id}")
async def viewer_ws(websocket: WebSocket, room_id: str):
    """Canal de salida: clientes (overlay de subtítulos) reciben
    TranscriptEvent / RoomStatusEvent por broadcast."""
    room = room_manager.get(room_id)
    if room is None:
        await websocket.close(code=4404)
        return
    await room.connections.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # no se espera input; mantiene viva la conexión
    except WebSocketDisconnect:
        pass
    finally:
        await room.connections.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
```

**Nota de diseño sobre el WS de ingesta**: no se expone un WebSocket para subir audio, porque el audio entra por RTMP/SRT directamente al FFmpeg embebido en cada `Room` (protocolo nativo que habla OBS). Lo que sí se expone es un control-plane HTTP (`POST /rooms/{id}/glossary`, `GET /rooms/{id}/status`) para operar la sala sin reiniciar el contenedor.

---

## 6. Manejo de audio (helper pendiente)

`app/audio/transforms.py` debe implementar `pcm_to_wav_base64(pcm_bytes, sample_rate)`: envuelve el buffer PCM crudo (ya en s16le/16kHz/mono gracias a FFmpeg) en un header WAV válido en memoria (módulo `wave` + `io.BytesIO`, sin tocar disco) y devuelve el resultado codificado en base64, listo para el bloque `input_audio` del punto 5. No requiere resampleo adicional porque FFmpeg ya normaliza sample rate/canales en la ingesta.

---

## 7. Camino de escalado a N salas

1. **Multi-room en un proceso**: `RoomManager` ya soporta registrar múltiples `Room`; agregar un endpoint `POST /rooms` que reciba `room_id`, puerto RTMP/SRT y glosario, e instancie una `Room` nueva. Limitación: cada `Room` necesita su propio puerto de ingesta (no se puede compartir el puerto 1935 entre salas).
2. **N contenedores del backend** (recomendado para producción): un `docker-compose` por sala (o un `docker-compose.override.yml` con servicios `backend-room1`, `backend-room2`, ...), cada uno con su propio puerto RTMP/SRT mapeado, todos apuntando al **mismo** contenedor `ollama` compartido. Ajustar `OLLAMA_NUM_PARALLEL` en función de cuántas salas hablan simultáneamente y de la memoria de la GPU (cada `gemma4:e2b` cargado consume VRAM; con `OLLAMA_MAX_LOADED_MODELS=1` todas las salas comparten la misma instancia del modelo, lo cual es deseable).

---

## 8. Próximos pasos (fuera de alcance de este documento)

- Implementar los archivos reales listados en la sección 1 a partir de los snippets de la sección 5.
- `frontend/overlay/`: cliente mínimo que se conecta a `/ws/room/{room_id}` y renderiza `TranscriptEvent` como subtítulos (browser source de OBS).
- `scripts/push_test_stream.sh`: script de prueba con `ffmpeg -re -i sample.wav -f flv rtmp://localhost:1935/live` para validar el pipeline end-to-end sin depender de OBS real.
- Tests: unitarios para `prompts.py` (formato del glosario), `glossary/loader.py` (parseo de YAML) y `transforms.py` (WAV válido); integración con un chunk de audio real contra un Ollama local.

---

## 9. Adaptación para la Vibeathon

Todo lo anterior quedó implementado (esqueleto completo, tests pasando, corrida real validada con FFmpeg + Ollama). Las bases de la Vibeathon de Nerdearla trajeron 5 requisitos puntuales que ajustaron el diseño original:

1. **Ingesta por archivo** (`FFmpegIngest`, `protocol="file"`): además de RTMP/SRT, FFmpeg puede leer un archivo local a velocidad real (`-re`) en loop (`-stream_loop -1`), para poder probar el proyecto clonando el repo sin necesitar OBS ni ningún push manual.
2. **Salida dual, siempre en los dos idiomas**: `InferenceResult`/`TranscriptEvent` pasaron de `{lang, text}` a `{lang, text_es, text_en}` — el prompt único (`app/inference/prompts.py:build_system_instructions`) le da al modelo la certeza de que el audio siempre está en español o inglés (nunca otro idioma) y le pide devolver siempre los dos campos (transcripción fiel del que se habló + traducción del otro), con un solo call a Ollama por chunk. También le exige usar solo caracteres de esos dos idiomas — reforzado con un filtro determinístico (`app/inference/sanitize.py`) que saca cualquier carácter de otro alfabeto de la respuesta, porque un modelo chico puede no respetar esa regla al 100%.
3. **N salas simultáneas por defecto, no solo documentadas**: `app/rooms/bootstrap.py:build_rooms()` arma una `Room` por cada id en `BABEL_ROOM_IDS` (`main,room2` por defecto) y `app/main.py` las arranca todas concurrentes. La Opción 1 de la sección 7 (multi-room en un proceso) pasó de ser una propuesta a ser el comportamiento real out-of-the-box; la Opción 2 (contenedores separados) sigue documentada en `docs/SCALING.md` para escalar más allá de lo que un proceso/GPU aguante.
4. **Convención de archivos de demo por sala**: `<demo_audio_dir>/<room_id>.wav` (fallback al fixture sintético si no existe) — alcanza con dejar un WAV con el nombre de la sala para tener una demo real sin tocar código ni config.
5. **`LICENSE` (MIT) y `README.md` reescrito** apuntando a los criterios de evaluación (sin credenciales externas, quickstart de 2 comandos, cómo probar con audio propio, cómo escalar).

Detalle completo de estos cambios (archivos tocados, tests nuevos) en `docs/ARCHITECTURE.md` y `docs/SCALING.md`, que quedaron actualizados para reflejar el comportamiento real.
