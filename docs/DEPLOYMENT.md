# Despliegue

## Prerequisitos del host

- Docker + Docker Compose v2 (soporte de `deploy.resources.reservations.devices`).
- GPU NVIDIA (T4/L4 o superior) recomendada para latencia baja. También corre en CPU (más lento) — Ollama cae a CPU automáticamente si no detecta GPU/toolkit, no requiere ningún cambio de config.
- Si hay GPU: driver NVIDIA instalado y funcionando (`nvidia-smi` sin errores) + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instalado (**reiniciar Docker después de instalarlo**).
- Puertos: `8000` (HTTP/WS) siempre. `1935`/`1936` (RTMP, una por sala) solo si se usa `BABEL_INGEST_PROTOCOL=rtmp` — en el modo `file` (default) no hace falta abrir nada más. `11434` solo si se necesita acceso externo a Ollama (normalmente no).

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

Por defecto (`BABEL_INGEST_PROTOCOL=file`) el stack levanta **2 salas** (`main`, `room2`) que ya arrancan ingiriendo en loop el audio de `tests/fixtures/` — no requiere ningún push manual. Ver [`frontend/dashboard/`](../frontend/dashboard/) para verlas ambas en una sola pantalla.

## Validar el pipeline

Con el modo `file` (default) no hace falta nada más que abrir el dashboard/overlay — ya está todo corriendo. Para probar el modo `rtmp` (stream real de OBS/consola) sin depender de OBS:

```bash
BABEL_INGEST_PROTOCOL=rtmp docker compose up -d
./scripts/push_test_stream.sh tests/fixtures/sample_audio_5s.wav localhost 1935
```

Mientras corre:
- `frontend/dashboard/index.html?api_host=localhost:8000` — todas las salas activas, en vivo, en una sola pantalla.
- `frontend/overlay/index.html?room=main&ws_host=localhost:8000` (agregar `&mode=reading` para el modo accesible) — subtítulos de una sala.
- `GET http://localhost:8000/rooms` — estado de todas las salas.
- `GET http://localhost:8000/rooms/main/status` — estado y tamaño de cola de una sala puntual.
- `GET http://localhost:8000/rooms/main/transcript.txt` — transcript acumulado, descargable.

## Producción

- **Nunca usar `latest`** para la imagen `ollama/ollama` una vez estabilizado el setup — pinnear una versión concreta.
- Ajustar `BABEL_MAX_QUEUE_SIZE`, `BABEL_CHUNK_SECONDS` y `OLLAMA_NUM_PARALLEL` según la latencia observada en vivo (ver `GET /rooms/{id}/status` para el tamaño de cola en tiempo real como señal de si el sistema está atrasado).
- Para más de 2 salas o escalar más allá de un solo proceso/GPU, ver [`SCALING.md`](SCALING.md).
