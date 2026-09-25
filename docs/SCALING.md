# Escalado a múltiples salas

El backend corre **N salas simultáneas dentro de un solo proceso** (por defecto 2: `main` y `room2`). `Room` encapsula toda la lógica de una sala (ingesta FFmpeg, cola, pipeline de inferencia, viewers); `app/rooms/bootstrap.py:build_rooms()` arma una `Room` por cada id en `BABEL_ROOM_IDS` y `app/main.py` las arranca todas de forma concurrente (cada `Room.start()` lanza sus propias tasks de asyncio, así que no compiten por bloquearse entre sí).

## Opción 1 — Multi-room en un solo proceso (comportamiento por defecto)

Ya está implementado. Para agregar salas alcanza con extender la variable de entorno:

```
BABEL_ROOM_IDS=main,room2,room3,room4
```

Cada sala nueva:
- Toma el siguiente puerto de ingesta automáticamente (`BABEL_INGEST_BASE_PORT` + índice) cuando `BABEL_INGEST_PROTOCOL=rtmp`.
- En modo `file`, busca `tests/fixtures/<room_id>.wav` (o cae al fixture de ejemplo si no existe ese archivo) — no requiere tocar `docker-compose.yml` si ese volumen ya está montado.
- Toma su propio glosario si existe `glossaries/<room_id>.yaml`, o el glosario global (`BABEL_GLOSSARY_PATH`) como fallback.

**Limitación**: si se usa `rtmp`, cada `Room` necesita su propio puerto expuesto en `docker-compose.yml` — hay que agregar el mapeo de puerto correspondiente por cada sala nueva (`docker-compose.yml` solo trae mapeados `1935`/`1936` de fábrica).

Ventaja: un solo proceso Python, más simple de operar. Desventaja: todas las salas compiten por el mismo event loop y la misma GPU sin aislamiento de recursos por contenedor — este modo sirve mientras un solo backend/GPU dé abasto para el tráfico combinado de todas las salas.

## Opción 2 — N contenedores del backend (recomendado en producción, más allá de lo que un proceso/GPU aguante)

Un `docker-compose.override.yml` (o un compose por sala) con servicios `backend-room1`, `backend-room2`, etc., cada uno con:

- Su propio puerto RTMP/SRT mapeado al host.
- Su propio `BABEL_ROOM_IDS` (con un solo id, ej. `BABEL_ROOM_IDS=room1`) y `BABEL_GLOSSARY_PATH`.
- Todos apuntando al **mismo** contenedor `ollama` compartido (`BABEL_OLLAMA_BASE_URL: http://ollama:11434/v1`).

Ajustar `OLLAMA_NUM_PARALLEL` en función de cuántas salas hablan simultáneamente y de la VRAM disponible. Mantener `OLLAMA_MAX_LOADED_MODELS=1` para que todas las salas compartan la misma instancia cargada de `gemma4:e2b` en memoria en vez de cargar una copia por sala.

## Mejoras de Fase 2 (no implementadas en el MVP)

- **Retrieval semántico de glosario**: para charlas con glosarios grandes (>40 términos), en vez de filtrar solo por el flag `core`, mantener una ventana de los últimos N textos emitidos y hacer fuzzy-match (`rapidfuzz`) o embeddings contra el glosario completo para traer solo los términos con más probabilidad de aparecer en el próximo chunk. Ver el `TODO` en `app/inference/prompts.py`.
- **Ingesta más robusta**: introducir un componente intermedio tipo MediaMTX o nginx-rtmp delante de FFmpeg para absorber reconexiones de OBS sin que el proceso FFmpeg tenga que reiniciarse por completo.
- **Detección de idioma como paso separado**: si el prompt único no detecta el idioma de forma confiable en producción, considerar un paso previo liviano de detección de idioma antes de decidir el prompt de transcripción vs. traducción.
