# Escalado a múltiples salas

El MVP corre **una sala por instancia del backend**. `Room` encapsula toda la lógica de una sala (ingesta FFmpeg, cola, pipeline de inferencia, viewers), así que escalar es cuestión de multiplicar `Room`, no de rediseñar nada.

## Opción 1 — Multi-room en un solo proceso

`RoomManager` ya soporta registrar múltiples `Room`. Para habilitarlo:

1. Agregar un endpoint `POST /rooms` que reciba `room_id`, puerto RTMP/SRT y ruta del glosario, instancie una `Room` nueva y la registre.
2. **Limitación**: cada `Room` necesita su propio puerto de ingesta — no se puede compartir el puerto 1935 entre salas, así que hay que asignar un rango de puertos (1935, 1936, 1937, ...) y comunicárselo a cada consola de sonido / OBS.

Ventaja: un solo proceso Python, más simple de operar. Desventaja: todas las salas compiten por el mismo event loop y la misma GPU sin aislamiento de recursos por contenedor.

## Opción 2 — N contenedores del backend (recomendado en producción)

Un `docker-compose.override.yml` (o un compose por sala) con servicios `backend-room1`, `backend-room2`, etc., cada uno con:

- Su propio puerto RTMP/SRT mapeado al host.
- Su propio `BABEL_ROOM_ID` y `BABEL_GLOSSARY_PATH`.
- Todos apuntando al **mismo** contenedor `ollama` compartido (`BABEL_OLLAMA_BASE_URL: http://ollama:11434/v1`).

Ajustar `OLLAMA_NUM_PARALLEL` en función de cuántas salas hablan simultáneamente y de la VRAM disponible. Mantener `OLLAMA_MAX_LOADED_MODELS=1` para que todas las salas compartan la misma instancia cargada de `gemma4:e2b` en memoria en vez de cargar una copia por sala.

## Mejoras de Fase 2 (no implementadas en el MVP)

- **Retrieval semántico de glosario**: para charlas con glosarios grandes (>40 términos), en vez de filtrar solo por el flag `core`, mantener una ventana de los últimos N textos emitidos y hacer fuzzy-match (`rapidfuzz`) o embeddings contra el glosario completo para traer solo los términos con más probabilidad de aparecer en el próximo chunk. Ver el `TODO` en `app/inference/prompts.py`.
- **Ingesta más robusta**: introducir un componente intermedio tipo MediaMTX o nginx-rtmp delante de FFmpeg para absorber reconexiones de OBS sin que el proceso FFmpeg tenga que reiniciarse por completo.
- **Detección de idioma como paso separado**: si el prompt único no detecta el idioma de forma confiable en producción, considerar un paso previo liviano de detección de idioma antes de decidir el prompt de transcripción vs. traducción.
