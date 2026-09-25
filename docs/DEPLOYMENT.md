# Despliegue

## Prerequisitos del host

- Docker + Docker Compose v2. Nada más — `docker-compose.yml` **no** reserva GPU, así que `docker compose up` anda en cualquier máquina (Mac, Windows, Linux, con o sin NVIDIA) sin fallar. Pero en CPU la inferencia es lenta de verdad (minutos por chunk, no segundos) — para latencia real hace falta uno de estos dos caminos de GPU:

  - **Linux con GPU NVIDIA** (ej. la VPS de producción): con el [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instalado (**reiniciar Docker después de instalarlo**) y `nvidia-smi` corriendo sin errores, sumar el override `docker-compose.gpu.yml`:
    ```bash
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
    ```

  - **Mac (con o sin Apple Silicon)**: Docker Desktop en Mac **no puede** pasarle la GPU del sistema a un contenedor Linux — el override de arriba no sirve acá, y Ollama dentro de Docker en Mac siempre va a usar CPU. La alternativa es Ollama **nativo** (fuera de Docker, usa la GPU del sistema automáticamente) + solo el backend en Docker, vía `docker-compose.local-ollama.yml` (ver sección siguiente).

  Sin ninguno de los dos, Ollama cae a CPU automáticamente — sin ningún cambio de config, pero lento.
- Puertos: `8000` (HTTP/WS) siempre. `1935`/`1936` (RTMP, una por sala) solo si se usa `BABEL_INGEST_PROTOCOL=rtmp` — en el modo `file` (default) no hace falta abrir nada más. `11434` solo si se necesita acceso externo a Ollama (normalmente no).

## Primer arranque en Mac (Ollama nativo — recomendado)

```bash
# 1. Instalar Ollama nativo (no en Docker): https://ollama.com/download
ollama pull gemma4:e2b        # usa la GPU (Metal) del sistema automáticamente
./scripts/check_local_ollama.sh    # valida que está todo listo antes de levantar Docker

docker compose -f docker-compose.local-ollama.yml up -d --build
docker compose -f docker-compose.local-ollama.yml logs -f backend
```

Este archivo solo levanta el `backend` (no `ollama`/`ollama-init` — no hacen falta, Ollama corre nativo). **Si el stack default (`docker-compose.yml`) estaba corriendo, bajalo primero con `docker compose down`** — su servicio `ollama` también ocupa el puerto 11434, y si queda arriba el backend termina hablándole a ese (el lento, en Docker) en vez de al nativo, sin ningún error visible — `check_local_ollama.sh` avisa si detecta este caso.

## Primer arranque

```bash
cp .env.example .env
# editar .env si hace falta: BABEL_ROOM_IDS, OLLAMA_MODEL, BABEL_SILENCE_RMS_THRESHOLD, etc.
# (docker-compose.yml lee estas variables via ${VAR:-default}, así que .env
# sí tiene efecto real sobre el stack — no hace falta tocar el compose)

docker compose up -d --build
docker compose logs -f backend
```

El servicio `ollama-init` descarga el modelo (`gemma4:e2b` por defecto) automáticamente la primera vez que el stack se levanta. Para forzar una descarga manual o cambiar de modelo más tarde:

```bash
./scripts/pull_model.sh gemma4:e4b
```

Por defecto el stack levanta **3 salas**: `main` y `room2` (`BABEL_INGEST_PROTOCOL=file`, audio de `tests/fixtures/`) y `mic` (forzada a modo micrófono vía `BABEL_MIC_ROOM_IDS=mic`, sin importar `BABEL_INGEST_PROTOCOL`). Las tres arrancan **inactivas** — `main`/`room2` en estado "paused" (nadie ingiere nada hasta activarlas) y `mic` en "waiting_for_mic" (esperando a que alguien grabe desde `frontend/mic/`). Activar `main`/`room2` es un click en "Reanudar" en el [control room](../frontend/dashboard/) (o `POST /rooms/{id}/resume`) — así arrancan solo cuando de verdad se las va a mostrar, sin competir por capacidad de inferencia con la sala mic desde el arranque.

## Validar el pipeline

Con el modo `file` (default) no hace falta nada más que abrir el dashboard/overlay — ya está todo corriendo. Para probar el modo `rtmp` (stream real de OBS/consola) sin depender de OBS:

```bash
BABEL_INGEST_PROTOCOL=rtmp docker compose up -d
./scripts/push_test_stream.sh tests/fixtures/sample_audio_5s.wav localhost 1935
```

Para probar la ingesta de micrófono (sala `mic`, siempre disponible sin importar `BABEL_INGEST_PROTOCOL`):

```bash
python3 -m http.server 8080 --directory frontend   # recomendado por sobre file://, ver README
open "http://localhost:8080/mic/index.html?ws_host=localhost:8000"
```

Mientras corre:
- `frontend/dashboard/index.html?api_host=localhost:8000` — todas las salas activas, en vivo, en una sola pantalla (con link directo a "🎙️ Grabar" en la card de `mic`).
- `frontend/overlay/index.html?room=main&ws_host=localhost:8000` (agregar `&mode=reading` para el modo accesible) — subtítulos de una sala.
- `GET http://localhost:8000/rooms` — estado de todas las salas (incluye `protocol` de cada una).
- `GET http://localhost:8000/rooms/main/status` — estado y tamaño de cola de una sala puntual.
- `GET http://localhost:8000/rooms/main/transcript.txt` — transcript acumulado, descargable.

## Producción

- **Nunca usar `latest`** para la imagen `ollama/ollama` una vez estabilizado el setup — pinnear una versión concreta.
- Ajustar `BABEL_MAX_QUEUE_SIZE`, `BABEL_CHUNK_SECONDS` y `OLLAMA_NUM_PARALLEL` según la latencia observada en vivo (ver `GET /rooms/{id}/status` para el tamaño de cola en tiempo real como señal de si el sistema está atrasado).
- Para más de 3 salas o escalar más allá de un solo proceso/GPU, ver [`SCALING.md`](SCALING.md).

### Recomendación de hardware para escalar a más salas

Lo medido en `main` de este repo es con una **GPU de laptop** (Apple Silicon, vía Metal, Ollama nativo) — no el hardware al que apunta el proyecto en producción (`PLAN.md` siempre pensó esto para una VPS con GPU de datacenter). Con una GPU de datacenter dedicada el cuadro mejora más: más VRAM (16-24GB+ vs. la memoria compartida de una laptop), soporte CUDA maduro en Ollama (generalmente más optimizado que el backend Metal), y cómputo sin competir con el resto del sistema operativo — margen para sostener bastantes más salas simultáneas con la misma latencia baja, o para charlas más largas/glosarios más grandes:

| GPU | VRAM | Uso recomendado |
|---|---|---|
| **NVIDIA T4** | 16 GB | Mínimo razonable — `gemma4:e2b` (7.2 GB) entra cómodo, buen margen para varias salas más con `OLLAMA_NUM_PARALLEL` ajustado a la cantidad activa. |
| **NVIDIA L4** | 24 GB | **Recomendada** — generación más nueva (Ada Lovelace) que T4, sustancialmente más rápida en inferencia sostenida, sigue siendo costo-efectiva para alquilar por el tiempo del evento. |
| **NVIDIA A10G / L40S** | 24-48 GB | Para escalar a muchas más salas en el mismo proceso sin aislar por contenedor (ver [`SCALING.md`](SCALING.md)), o usar `gemma4:e4b` (mayor calidad) sin perder velocidad. |

Estos números de VRAM son una recomendación razonada (el modelo entra cómodo con margen para el KV-cache de varias salas en paralelo), **no un benchmark corrido en esa GPU real** — no hubo acceso a una durante el desarrollo. Antes de una demo sobre una VPS con GPU, vale la pena una prueba rápida: levantar `docker-compose.gpu.yml`, pullear el modelo, y mandar un par de chunks reales (`scripts/push_test_stream.sh` o directo por `/ws/mic/{id}`) para confirmar la demora real en ese hardware específico, y ajustar `OLLAMA_NUM_PARALLEL` para que coincida con la cantidad de salas activas.
