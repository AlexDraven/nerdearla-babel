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

- Recibe audio en vivo desde **tu propio micrófono** (eligiendo el dispositivo desde el navegador), desde RTMP/SRT (OBS o una consola de sonido), **o** desde un archivo de audio local (para probar sin infraestructura).
- Transcribe en tiempo real en el idioma original (español o inglés).
- Traduce en tiempo real a español (configurable a cualquier otro idioma objetivo — ver [`.env.example`](.env.example)).
- Muestra los subtítulos en un overlay web (usable como browser source de OBS, o en cualquier navegador).
- Procesa **3 sesiones/salas en simultáneo por defecto** (2 de demo + 1 de micrófono en vivo), con arquitectura lista para escalar a más.

## Sin credenciales externas

Todo el procesamiento (audio → transcripción → traducción) corre localmente vía [Ollama](https://ollama.com) + el modelo `gemma4:e2b` (Gemma 4, con soporte nativo de audio). **No hace falta ninguna API key ni cuenta externa.** Lo único que se necesita es Docker + Docker Compose v2 — no hace falta GPU (ver nota abajo).

### Nota sobre GPU — importante para que la transcripción responda rápido

`docker compose up` (el comando de abajo, tal cual) corre **en cualquier máquina**, con o sin GPU — nunca falla. Pero la inferencia en CPU es lenta de verdad (un solo chunk de audio puede tardar varios minutos, no segundos) — para una demo en vivo hace falta GPU. Elegí según tu hardware:

- **🍎 Mac (con o sin Apple Silicon) → Ollama nativo, recomendado.** Docker Desktop en Mac **no puede** pasarle la GPU del sistema a un contenedor Linux — así que Ollama corriendo *dentro* de Docker en Mac siempre usa CPU, sin excepción. La solución es instalar Ollama nativo (no en Docker) — usa la GPU del sistema (Metal) automáticamente — y solo el backend en Docker:
  ```bash
  # 1. Instalar Ollama nativo: https://ollama.com/download
  ollama pull gemma4:e2b
  ./scripts/check_local_ollama.sh                          # valida que está todo listo
  docker compose -f docker-compose.local-ollama.yml up -d --build
  ```
  Importante: si ya tenías el stack default (`docker-compose.yml`) corriendo, bajalo primero con `docker compose down` — su servicio `ollama` también ocupa el puerto 11434, y si sigue arriba el backend termina hablándole a ese (el lento) en vez de al nativo, sin ningún error visible.

- **🐧 Linux con GPU NVIDIA** (ej. la VPS real de producción) → sumar el override de GPU:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
  ```
  Requiere el [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instalado.

- **Ningún GPU disponible** → el comando default de abajo funciona igual, pero esperá que cada chunk tarde bastante — no es la mejor forma de mostrar el proyecto en vivo.

## Quickstart (probar en 2 comandos)

```bash
cp .env.example .env   # opcional, .env.example ya trae defaults razonables
docker compose up -d --build
```

El backend (FastAPI + las 3 salas) queda arriba en segundos — **no hace falta esperar nada** para ver que el sistema está vivo y procesando en simultáneo (`docker compose logs -f backend`, o directo el control room, un poco más abajo). En paralelo, el servicio `ollama-init` descarga `gemma4:e2b` (**~7 GB**, la primera vez) — hasta que termine, cada chunk de audio loguea un error 404 controlado ("model not found") en vez de trabar nada; apenas termina la descarga, los subtítulos con contenido real empiezan a aparecer solos, sin reiniciar nada. En una conexión hogareña normal puede tardar bastante más que "un par de minutos" — para no depender de esa espera al mostrar el proyecto, conviene dejar `docker compose up -d --build` corriendo un rato antes de grabar/demostrar (`docker compose logs -f ollama-init` para ver el progreso de la descarga).

Ya con eso hay **3 salas corriendo en simultáneo**: `main` y `room2` en loop sobre un archivo de audio de `tests/fixtures/` (modo `file`, sin necesidad de OBS ni ningún push manual), y `mic` esperando a que alguien hable a su propio micrófono (ver la sección siguiente).

La forma más rápida de ver que las 3 salas están vivas y en paralelo es el **control room**:

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

## Probar con tu propio micrófono

La sala `mic` (una de las 3 que levanta el stack por defecto) está pensada exactamente para esto — nadie tiene que tocar audio pregrabado ni configurar nada.

```bash
# recomendado: servir frontend/ por HTTP (evita cualquier duda de permisos
# de mic en un navegador que no es el tuyo — file:// también debería andar,
# pero esta es la opción más robusta para probar en vivo frente a alguien)
python3 -m http.server 8080 --directory frontend
open "http://localhost:8080/mic/index.html?ws_host=localhost:8000"
```

En la página: el navegador pide permiso de micrófono, elegís el dispositivo de entrada en el desplegable (sirve para elegir entre el mic integrado y uno externo/headset), apretás **Grabar**, hablás — y la transcripción/traducción aparece en la misma página en vivo. Funciona en Chrome, Edge y Firefox (usa `MediaRecorder` con `audio/webm;codecs=opus`; si el navegador no lo soporta —ej. Safari viejo— la página lo avisa en vez de fallar en silencio).

## Audio de demo incluido / usar el tuyo propio

El repo ya incluye audio de habla real para las 2 salas de demo (`main`/`room2`): `tests/fixtures/main.wav` (charla en español) y `tests/fixtures/room2.wav` (charla en inglés, para mostrar el caso transcripción + traducción) — no hace falta ningún paso extra, se usan solos apenas se levanta el stack. `tests/fixtures/sample_audio_5s.wav` (un tono sintético) queda solo como fixture de los tests automatizados.

Para reemplazarlos por tus propios clips:

1. Conseguí 1-2 clips cortos de habla real (por ejemplo, de una charla vieja de Nerdearla en YouTube).
2. Sobreescribí `tests/fixtures/main.wav` y/o `tests/fixtures/room2.wav` (formato WAV; si no lo tenés en WAV, `ffmpeg -i entrada.mp3 tests/fixtures/main.wav` lo convierte).
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

## Escalar a más de 3 salas

Alcanza con editar una variable de entorno — no hace falta tocar código:

```
BABEL_ROOM_IDS=main,room2,mic,room4,room5
```

Cada sala nueva de tipo `file`/`rtmp` toma el siguiente puerto de ingesta automáticamente y comparte la misma instancia de Ollama (con `OLLAMA_MAX_LOADED_MODELS=1`, todas usan el mismo modelo cargado en memoria, sin duplicar VRAM). Para agregar otra sala de micrófono (ej. dos jurados grabando a la vez), sumar su id también a `BABEL_MIC_ROOM_IDS` (ej. `BABEL_MIC_ROOM_IDS=mic,mic2`) y abrir `frontend/mic/index.html?room=mic2`. Este modo ("multi-room en un proceso") sirve mientras un solo backend/GPU dé abasto. Para escalar más allá de eso en producción real (aislar recursos por sala, distribuir entre varias GPUs/VPS), ver [`docs/SCALING.md`](docs/SCALING.md).

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
frontend/mic/        grabar con tu propio micrófono (elegir dispositivo) y ver la transcripción en vivo
glossaries/          glosarios técnicos por charla (YAML) — glossaries/<room_id>.yaml
tests/fixtures/      audios de demo (uno por sala, por convención <room_id>.wav)
scripts/             utilidades (pull de modelo, push de stream de prueba)
docs/                arquitectura, escalado a N salas, despliegue
```

## Licencia

[MIT](LICENSE).
