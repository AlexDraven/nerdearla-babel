# nerdearla-babel

Subtítulos en vivo, self-hosted, para charlas de conferencias de tecnología: transcripción en el idioma original (ES o EN) **y** traducción a español en tiempo real, corriendo 100% en tu propia infraestructura — sin SaaS, sin pagar por minuto, sin mandar audio a un tercero.

Construido para la [Vibeathon de Nerdearla](https://nerdearla.com) (24-25 de septiembre de 2026).

📹 **Video demo**: _[completar con el link de YouTube antes de entregar]_

## Qué hace

- Recibe audio en vivo desde **tu propio micrófono** (eligiendo el dispositivo desde el navegador), desde RTMP/SRT (OBS o una consola de sonido), o desde un archivo de audio local (para probar sin infraestructura).
- Transcribe en tiempo real y **siempre entrega los subtítulos en los dos idiomas a la vez** (español e inglés) — el modelo sabe que la charla solo puede estar en uno de esos dos, nunca en otro, y solo puede escribir con caracteres de esos idiomas.
- Muestra los subtítulos en un overlay web (browser source de OBS o cualquier navegador), con un **modo lectura accesible** (historial con scroll, control de tamaño de letra/contraste, `aria-live` para lectores de pantalla).
- Procesa **3 sesiones/salas en simultáneo por defecto**, con un **control room** ([`frontend/dashboard/`](frontend/dashboard/)) que las muestra todas juntas en vivo — estado, cola y latencia real de cada una, con la grabación por micrófono embebida ahí mismo y un botón para pausar/reanudar las salas de demo (ej. para liberarle capacidad a la sala mic mientras alguien graba).
- Guarda un **transcript persistente y exportable** por sala (no solo subtítulos que desaparecen) en `GET /rooms/{id}/transcript.txt`.
- Inyecta un **glosario técnico** (nombres de librerías, spanglish, speakers) en cada chunk para no perder precisión en jerga — verificable en `GET /rooms/{id}/glossary`.

Todo el procesamiento (audio → transcripción → traducción) corre localmente vía [Ollama](https://ollama.com) + `gemma4:e2b` (Gemma 4, con soporte nativo de audio). **No hace falta ninguna API key ni cuenta externa.**

## Quickstart

```bash
cp .env.example .env   # opcional, .env.example ya trae defaults razonables
docker compose up -d --build
```

Levanta el backend y las 3 salas: `main`/`room2` (audio de demo real en `tests/fixtures/`) y `mic` (para hablarle a tu propio micrófono) — **las 3 arrancan pausadas**, para no competir por capacidad de inferencia entre sí desde el arranque. La primera vez, `ollama-init` descarga el modelo (~7 GB) en paralelo.

Abrí el control room y activá las que quieras probar (botón "Reanudar" en `main`/`room2`, o "Grabar" en `mic`):

```bash
open "frontend/dashboard/index.html?api_host=localhost:8000"   # macOS; Linux: xdg-open
```

Y por línea de comandos:

```bash
curl http://localhost:8000/rooms                      # lista todas las salas activas
curl http://localhost:8000/rooms/main/transcript.txt   # transcript acumulado de la sala "main"
```

### GPU (recomendado para latencia real)

`docker compose up` corre **en cualquier máquina**, con o sin GPU — nunca falla. Pero sin GPU, un chunk de audio puede tardar minutos en vez de segundos:

- **Mac**: Docker Desktop no puede pasarle la GPU del sistema a un contenedor Linux — instalar [Ollama nativo](https://ollama.com/download) y levantar solo el backend en Docker:
  ```bash
  ollama pull gemma4:e2b
  docker compose -f docker-compose.local-ollama.yml up -d --build
  ```
- **Linux con GPU NVIDIA**: sumar el override de GPU (requiere el [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
  ```

Con una GPU de laptop (la usada en desarrollo) el sistema ya sostiene las 3 salas por defecto con ~2-4s de demora audio→texto. Con una GPU de datacenter (más VRAM, CUDA maduro, sin competir por cómputo con el resto del SO) el mismo sistema escala a **bastantes más salas simultáneas** sin perder esa latencia — ver [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) para la tabla de GPUs recomendadas y troubleshooting.

## Probar con tu propio micrófono

```bash
python3 -m http.server 8080 --directory frontend
open "http://localhost:8080/mic/index.html?ws_host=localhost:8000"
```

Elegís el dispositivo de entrada, apretás **Grabar**, hablás — y la transcripción/traducción aparece en vivo en la misma página. Funciona en Chrome, Edge y Firefox.

## Más allá del quickstart

- **Reemplazar el audio de demo** por tus propios clips, o **usar un stream real** (OBS/consola de sonido) en vez de los archivos de `tests/fixtures/` → [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
- **Escalar a más de 3 salas** → alcanza con una variable de entorno (`BABEL_ROOM_IDS`), sin tocar código → [`docs/SCALING.md`](docs/SCALING.md).
- **Arquitectura completa** (flujo async, backpressure, estrategia de glosario, por qué Ollama necesita el endpoint OpenAI-compatible para audio) → [`PLAN.md`](PLAN.md) y [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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
