# Despliegue

## Prerequisitos del host

- VPS Linux con GPU NVIDIA (T4/L4 o superior).
- Driver NVIDIA instalado y funcionando (`nvidia-smi` debe correr sin errores).
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instalado — **reiniciar Docker después de instalarlo**.
- Docker Compose v2 (soporte de `deploy.resources.reservations.devices`).
- Puertos abiertos en el firewall: `8000` (HTTP/WS), `1935` (RTMP) o `9998/udp` (SRT) según el protocolo de ingesta elegido, `11434` solo si se necesita acceso externo a Ollama (normalmente no).

## Primer arranque

```bash
cp .env.example .env
# editar .env: BABEL_ROOM_ID, OLLAMA_MODEL, BABEL_GLOSSARY_PATH, etc.

docker compose up -d
docker compose logs -f backend
```

El servicio `ollama-init` descarga el modelo (`gemma4:e2b` por defecto) automáticamente la primera vez que el stack se levanta. Para forzar una descarga manual o cambiar de modelo más tarde:

```bash
./scripts/pull_model.sh gemma4:e4b
```

## Validar el pipeline sin OBS real

```bash
./scripts/push_test_stream.sh tests/fixtures/sample_audio_5s.wav
```

Mientras corre, abrir `frontend/overlay/index.html?ws_host=localhost:8000` en un navegador (o como browser source en OBS) para ver los subtítulos en vivo, y `GET http://localhost:8000/rooms/main/status` para ver el estado de la sala y el tamaño de la cola.

## Producción

- **Nunca usar `latest`** para la imagen `ollama/ollama` una vez estabilizado el setup — pinnear una versión concreta.
- Ajustar `BABEL_MAX_QUEUE_SIZE`, `BABEL_CHUNK_SECONDS` y `OLLAMA_NUM_PARALLEL` según la latencia observada en vivo (ver `GET /rooms/{id}/status` para el tamaño de cola en tiempo real como señal de si el sistema está atrasado).
- Para múltiples salas, ver [`SCALING.md`](SCALING.md).
