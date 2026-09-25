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
# editar .env si hace falta: BABEL_ROOM_IDS, OLLAMA_MODEL, BABEL_TARGET_LANG, etc.
# (docker-compose.yml lee estas variables via ${VAR:-default}, así que .env
# sí tiene efecto real sobre el stack — no hace falta tocar el compose)

docker compose up -d --build
docker compose logs -f backend
```

El servicio `ollama-init` descarga el modelo (`gemma4:e2b` por defecto) automáticamente la primera vez que el stack se levanta. Para forzar una descarga manual o cambiar de modelo más tarde:

```bash
./scripts/pull_model.sh gemma4:e4b
```

Por defecto el stack levanta **3 salas**: `main` y `room2` (`BABEL_INGEST_PROTOCOL=file`) ya arrancan ingiriendo en loop el audio de `tests/fixtures/` — no requiere ningún push manual — y `mic` (forzada a modo micrófono vía `BABEL_MIC_ROOM_IDS=mic`, sin importar `BABEL_INGEST_PROTOCOL`) queda esperando a que alguien grabe desde `frontend/mic/`. Ver [`frontend/dashboard/`](../frontend/dashboard/) para verlas las 3 en una sola pantalla.

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
