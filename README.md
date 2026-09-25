# nerdearla-babel

Subtítulos en vivo, self-hosted, para charlas de conferencias de tecnología: transcripción en el idioma original (ES o EN) **y** traducción a español en tiempo real, corriendo 100% en tu propia infraestructura — sin SaaS, sin pagar por minuto, sin mandar audio a un tercero.

Construido para la [Vibeathon de Nerdearla](https://nerdearla.com) (24-25 de septiembre de 2026).

📹 **Video demo**: _[completar con el link de YouTube antes de entregar]_

## Qué nos diferencia

Más allá del MVP (transcripción + traducción + multi-sala), 4 cosas que probablemente no todos los proyectos tengan:

- 🗂️ **Transcript persistente y exportable**, no solo subtítulos que desaparecen — cada sala guarda su historial y lo expone en `GET /rooms/{id}/transcript.txt` (para publicar la charla después, o para alguien que no pudo seguirla en vivo).
- 🖥️ **[Control room](frontend/dashboard/index.html)**: una sola pantalla que muestra todas las salas activas en simultáneo, con estado, cola y latencia real de cada una — prueba visual de "N sesiones en paralelo" sin tener que abrir pestaña por pestaña.
- ♿ **Modo lectura accesible** en el overlay (`?mode=reading`): historial con scroll (no efímero), control de tamaño de letra y alto contraste, y `aria-live` para lectores de pantalla — pensado para alguien siguiendo la charla desde su propia laptop, no solo para un cartel de OBS.
- 🧠 **Glosario técnico anti-alucinaciones** inyectado en cada chunk (nombres de librerías, spanglish, speakers) para no perder precisión en jerga técnica — verificable en `GET /rooms/{id}/glossary`.

## Qué hace

- Recibe audio en vivo (RTMP/SRT desde OBS o una consola de sonido) **o** un archivo de audio local (para probar sin infraestructura).
- Transcribe en tiempo real en el idioma original (español o inglés).
- Traduce en tiempo real a español (configurable a cualquier otro idioma objetivo — ver [`.env.example`](.env.example)).
- Muestra los subtítulos en un overlay web (usable como browser source de OBS, o en cualquier navegador).
- Procesa **2 sesiones/salas en simultáneo por defecto**, con arquitectura lista para escalar a más.

## Sin credenciales externas

Todo el procesamiento (audio → transcripción → traducción) corre localmente vía [Ollama](https://ollama.com) + el modelo `gemma4:e2b` (Gemma 4, con soporte nativo de audio). **No hace falta ninguna API key ni cuenta externa.** Lo único que se necesita es:

- Docker + Docker Compose v2.
- GPU NVIDIA (recomendado para latencia baja; también corre en CPU, más lento — ver [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).

## Quickstart (probar en 2 comandos)

```bash
cp .env.example .env
docker compose up -d --build
```

El servicio `ollama-init` descarga `gemma4:e2b` automáticamente la primera vez (puede tardar unos minutos). Cuando el backend esté arriba (`docker compose logs -f backend`), ya hay **2 salas corriendo en simultáneo** (`main` y `room2`), cada una en loop sobre un archivo de audio de `tests/fixtures/` (modo `file`, sin necesidad de OBS ni ningún push manual).

La forma más rápida de ver que las 2 salas están vivas y en paralelo es el **control room**:

```bash
open "frontend/dashboard/index.html?api_host=localhost:8000"   # macOS
# Linux: xdg-open "frontend/dashboard/index.html?api_host=localhost:8000"
```

Ahí se ve una card por sala, actualizándose en vivo (estado, cola, latencia y último subtítulo). Desde cada card se puede saltar directo a su overlay o a su transcript.

También se puede abrir el overlay de cada sala directamente — es un archivo estático, se abre desde el filesystem, no lo sirve el backend:

```bash
open "frontend/overlay/index.html?room=main&ws_host=localhost:8000"                 # modo OBS (cartel efímero)
open "frontend/overlay/index.html?room=main&ws_host=localhost:8000&mode=reading"    # modo lectura accesible (historial + controles)
```

Y por línea de comandos:

```bash
curl http://localhost:8000/rooms                      # lista todas las salas activas
curl http://localhost:8000/rooms/main/transcript.txt   # transcript acumulado de la sala "main"
```

## Probar con tus propios audios

El repo incluye `tests/fixtures/sample_audio_5s.wav` (un tono sintético, solo para validar la plomería — **no** genera una transcripción con sentido). Para una demo real:

1. Conseguí 1-2 clips cortos de habla real (por ejemplo, de una charla vieja de Nerdearla en YouTube — uno en español y otro en inglés, para mostrar ambos casos: transcripción directa vs. transcripción + traducción).
2. Guardalos como `tests/fixtures/main.wav` y `tests/fixtures/room2.wav` (formato WAV; si no lo tenés en WAV, `ffmpeg -i entrada.mp3 tests/fixtures/main.wav` lo convierte).
3. `docker compose restart backend` — cada sala detecta el archivo por convención (`<room_id>.wav`) sin tocar código ni config.

## Usar con un stream real (OBS / consola de sonido)

Cambiá en `.env`:

```
BABEL_INGEST_PROTOCOL=rtmp
```

y reiniciá. Cada sala escucha en `BABEL_INGEST_BASE_PORT + índice` (por defecto: `main` → `1935`, `room2` → `1936`). Apuntá OBS (Configuración → Emisión → Servidor personalizado) a `rtmp://<host>:1935/live` para `main`, o probalo sin OBS con:

```bash
./scripts/push_test_stream.sh tests/fixtures/sample_audio_5s.wav localhost 1935   # o tu propio audio
```

## Escalar a más de 2 salas

Alcanza con editar una variable de entorno — no hace falta tocar código:

```
BABEL_ROOM_IDS=main,room2,room3,room4
```

Cada sala nueva toma el siguiente puerto de ingesta automáticamente y comparte la misma instancia de Ollama (con `OLLAMA_MAX_LOADED_MODELS=1`, todas usan el mismo modelo cargado en memoria, sin duplicar VRAM). Este modo ("multi-room en un proceso") sirve mientras un solo backend/GPU dé abasto. Para escalar más allá de eso en producción real (aislar recursos por sala, distribuir entre varias GPUs/VPS), ver [`docs/SCALING.md`](docs/SCALING.md).

## Arquitectura

Diseño completo (flujo asíncrono, backpressure, estrategia de glosario técnico, decisiones de por qué Ollama necesita el endpoint OpenAI-compatible para audio) en [`PLAN.md`](PLAN.md) y [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Desarrollo y tests (sin Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Requiere `ffmpeg` instalado localmente (`brew install ffmpeg` / `apt install ffmpeg`) para correr el backend fuera de Docker.

## Estructura

```
app/                backend FastAPI (audio, glosario, inferencia, salas, websockets)
frontend/overlay/    overlay de subtítulos — modo OBS (?mode=broadcast, default) o accesible (?mode=reading)
frontend/dashboard/  control room: todas las salas activas, en vivo, en una sola pantalla
glossaries/          glosarios técnicos por charla (YAML) — glossaries/<room_id>.yaml
tests/fixtures/      audios de demo (uno por sala, por convención <room_id>.wav)
scripts/             utilidades (pull de modelo, push de stream de prueba)
docs/                arquitectura, escalado a N salas, despliegue
```

## Licencia

[MIT](LICENSE).
