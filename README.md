# nerdearla-babel

Transcripción en vivo (ES → ES) y traducción (EN → ES) para charlas de conferencias de tecnología, 100% self-hosted: FFmpeg + FastAPI/asyncio + Ollama (Gemma 4). Pensado para reemplazar herramientas SaaS de captioning pagas por minuto y escalar a múltiples salas en un VPS con GPU propio.

Ver [`PLAN.md`](PLAN.md) para el diseño técnico completo y [`docs/`](docs/) para arquitectura, escalado y despliegue.

## Quickstart

```bash
cp .env.example .env
docker compose up -d --build
```

Ollama descarga el modelo (`gemma4:e2b` por defecto) automáticamente en el primer arranque vía el servicio `ollama-init`. OBS (o la consola de sonido de la sala) empuja el stream a `rtmp://<host>:1935/live`; los subtítulos se transmiten a `ws://<host>:8000/ws/room/main` y se pueden ver con `frontend/overlay/index.html` como browser source en OBS.

Para probar el pipeline sin un stream real: `./scripts/push_test_stream.sh <archivo-de-audio>`.

## Desarrollo local (sin Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Estructura

```
app/            backend FastAPI (audio, glosario, inferencia, salas, websockets)
frontend/overlay/   overlay de subtítulos para usar como browser source en OBS
glossaries/     glosarios técnicos por charla (YAML)
scripts/        utilidades (pull de modelo, stream de prueba)
docs/           arquitectura, escalado a N salas, despliegue
tests/          unitarios e integración
```
