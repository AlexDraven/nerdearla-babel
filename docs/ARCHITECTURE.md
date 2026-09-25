# Arquitectura

Ver [`PLAN.md`](../PLAN.md) para el diseño completo con snippets de código. Este documento resume el flujo de datos para referencia rápida.

```
OBS/consola/archivo  ──RTMP/SRT/file──▶  FFmpeg (subprocess)  ──PCM s16le stdout──▶
   │                                                                    │
   │                                                        readexactly(chunk_bytes)
   │                                                                    ▼
   │                                              Producer loop (Room._produce)
   │                                                                    │
   │                                              queue.put_nowait()  (maxsize=2,
   │                                              drop-oldest si está llena)
   │                                                                    ▼
   │                                                          asyncio.Queue
   │                                                                    │
   │                                          N workers (InferencePipeline.run)
   │                                                await queue.get()
   │                                                                    ▼
   │                                    PCM -> WAV -> base64  ->  build_messages(glosario, target_lang)
   │                                                                    ▼
   │                                    AsyncOpenAI(base_url=ollama).chat.completions.create(
   │                                        model, messages, response_format=json_object)
   │                                                                    ▼
   │                                    InferenceResult{lang, original_text, translated_text}
   │                                                                    ▼
Viewers ◀── WS broadcast (ConnectionManager) ◀── TranscriptEvent
```

Este flujo corre **una vez por sala**, y `app/rooms/bootstrap.py:build_rooms()` instancia una `Room` (con su propio FFmpeg, cola y pipeline) por cada id en `BABEL_ROOM_IDS` — por defecto 2 (`main`, `room2`), corriendo en simultáneo dentro del mismo proceso `asyncio`, todas contra el mismo Ollama.

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `app/audio/ffmpeg_ingest.py` | Levanta y supervisa el subprocess FFmpeg. Soporta 3 modos: `rtmp`/`srt` (servidor en vivo) y `file` (lee un archivo local a velocidad real, en loop — usado para la demo sin infraestructura). Entrega PCM en chunks de tamaño exacto. |
| `app/audio/transforms.py` | Envuelve PCM crudo en un WAV válido en memoria y lo codifica en base64. |
| `app/glossary/` | Modelo y loader del glosario técnico por charla (YAML). |
| `app/inference/prompts.py` | Construye el prompt único (detección de idioma + transcripción/traducción a `target_lang`) con el glosario inyectado. |
| `app/inference/ollama_client.py` | Cliente OpenAI-compatible contra Ollama — **nunca** usar `/api/chat` para audio. |
| `app/inference/pipeline.py` | Consumer async: toma chunks de la cola, llama a Ollama, emite `TranscriptEvent` (con `original_text` y `translated_text`). |
| `app/rooms/room.py` | Unidad de escalado: une ingesta + cola + pipeline + viewers de una sala. |
| `app/rooms/bootstrap.py` | Arma la lista de `Room` a partir de `BABEL_ROOM_IDS`, resolviendo el glosario y el audio de demo de cada una por convención de archivo. |
| `app/ws/connection_manager.py` | Broadcast de eventos a los viewers WS conectados. |
| `app/main.py` | FastAPI: lifecycle de **todas** las `Room` (arrancan concurrentes), endpoints de control y WS de salida. |

## Decisión: un solo prompt, con salida dual (no dos pipelines)

En vez de mantener flujos separados para "transcripción" y "traducción", se usa un único prompt que le pide al modelo detectar el idioma y devolver **ambos** campos en la misma respuesta: `original_text` (transcripción fiel en el idioma hablado) y `translated_text` (traducción a `BABEL_TARGET_LANG`, por defecto español; si el idioma original ya coincide con el target, ambos campos son iguales). Esto cumple los dos requisitos por separado (transcripción del idioma original + traducción) sin duplicar la lógica de manejo de errores/timeouts — sigue siendo un solo call a Ollama por chunk. Si en producción la detección de idioma del modelo resulta poco confiable, la alternativa es correr un paso previo liviano de detección de idioma (ver `docs/SCALING.md` para más mejoras de Fase 2).
