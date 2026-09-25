# Arquitectura

Ver [`PLAN.md`](../PLAN.md) para el diseño completo con snippets de código. Este documento resume el flujo de datos para referencia rápida.

```
OBS/consola/archivo/mic  ──RTMP/SRT/file/mic──▶  FFmpeg (subprocess)  ──PCM s16le stdout──▶
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

Este flujo corre **una vez por sala**, y `app/rooms/bootstrap.py:build_rooms()` instancia una `Room` (con su propio FFmpeg, cola y pipeline) por cada id en `BABEL_ROOM_IDS` — por defecto 3 (`main`, `room2` en modo `file`; `mic` forzada a modo `mic` vía `BABEL_MIC_ROOM_IDS`), corriendo en simultáneo dentro del mismo proceso `asyncio`, todas contra el mismo Ollama.

### Modo `mic`: ingesta desde el navegador, no desde la red

A diferencia de `rtmp`/`srt` (ffmpeg escucha un puerto) y `file` (ffmpeg lee un archivo), el modo `mic` hace que ffmpeg lea de **su propio stdin** (`-f webm -i pipe:0`). El navegador captura el micrófono con `MediaRecorder` (`audio/webm;codecs=opus`, ver `frontend/mic/app.js`) y manda los blobs por un WebSocket de **entrada** nuevo, `@app.websocket("/ws/mic/{room_id}")` (`app/main.py`), que los vuelca al stdin de ffmpeg vía `FFmpegIngest.write()`.

El punto delicado: cada sesión de grabación nueva (`MediaRecorder` nuevo) manda un header WebM nuevo, así que **cada sesión necesita un ffmpeg limpio** — reusar uno que ya consumió un header de una sesión anterior corrompe el parseo. Por eso una sala en modo `mic` usa un loop de supervisión distinto (`Room._supervised_mic_loop`) que, a diferencia del loop genérico (`_supervised_ingest_loop`, con reintento automático por backoff para rtmp/srt/file), **no reintenta por su cuenta**: solo arranca/reinicia ffmpeg cuando `Room.restart_mic_ingest()` lo dispara explícitamente (llamado únicamente por el WS de ingesta). Si el loop genérico reintentara también acá, competiría con el WS por el ciclo de vida del mismo proceso ffmpeg y terminaría matando una sesión de grabación en curso sin que el navegador se entere.

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `app/audio/ffmpeg_ingest.py` | Levanta y supervisa el subprocess FFmpeg. Soporta 4 modos: `rtmp`/`srt` (servidor en vivo), `file` (lee un archivo local a velocidad real, en loop — usado para la demo sin infraestructura) y `mic` (lee WebM/Opus de su propio stdin, alimentado por `/ws/mic/{id}`). Entrega PCM en chunks de tamaño exacto; `write()` alimenta el stdin en modo `mic`. |
| `app/audio/transforms.py` | Envuelve PCM crudo en un WAV válido en memoria y lo codifica en base64. |
| `app/glossary/` | Modelo y loader del glosario técnico por charla (YAML). |
| `app/inference/prompts.py` | Construye el prompt único (detección de idioma + transcripción/traducción a `target_lang`) con el glosario inyectado. |
| `app/inference/ollama_client.py` | Cliente OpenAI-compatible contra Ollama — **nunca** usar `/api/chat` para audio. |
| `app/inference/pipeline.py` | Consumer async: toma chunks de la cola, llama a Ollama, emite `TranscriptEvent` (con `original_text` y `translated_text`). |
| `app/rooms/room.py` | Unidad de escalado: une ingesta + cola + pipeline + viewers de una sala. También acumula `transcript` (deque, cap 5000 eventos), expone `transcript_as_text()`, y en modo `mic` usa `_supervised_mic_loop`/`restart_mic_ingest()` en vez del loop de reintento genérico (ver más abajo). |
| `app/rooms/bootstrap.py` | Arma la lista de `Room` a partir de `BABEL_ROOM_IDS`, resolviendo el glosario y el audio de demo de cada una por convención de archivo, y forzando modo `mic` para los ids en `BABEL_MIC_ROOM_IDS`. |
| `app/ws/connection_manager.py` | Broadcast de eventos a los viewers WS conectados. |
| `app/main.py` | FastAPI: lifecycle de **todas** las `Room` (arrancan concurrentes), endpoints de control (`/rooms`, `/rooms/{id}/status`, `/transcript`, `/transcript.txt`, `/glossary`), WS de salida (`/ws/room/{id}`) y WS de entrada de micrófono (`/ws/mic/{id}`). CORS abierto para que el overlay/dashboard/mic (archivos estáticos, otro origen) puedan consumirlo. |
| `frontend/dashboard/` | Control room: pollea `GET /rooms` + abre un WS por sala para mostrar todas las sesiones activas en una sola pantalla (estado, cola, latencia, último subtítulo, link directo a grabar si es una sala `mic`). |
| `frontend/overlay/` | Dos modos sobre el mismo WS: `broadcast` (default, cartel efímero para OBS) y `?mode=reading` (scrollback + control de fuente/contraste + `aria-live`, para seguir la charla desde el propio dispositivo). |
| `frontend/mic/` | Captura el micrófono elegido por el usuario (`MediaRecorder`), lo manda a `/ws/mic/{id}` y muestra la transcripción en vivo en la misma página (WS de salida, igual que el overlay). |

## Decisión: un solo prompt, con salida dual (no dos pipelines)

En vez de mantener flujos separados para "transcripción" y "traducción", se usa un único prompt que le pide al modelo detectar el idioma y devolver **ambos** campos en la misma respuesta: `original_text` (transcripción fiel en el idioma hablado) y `translated_text` (traducción a `BABEL_TARGET_LANG`, por defecto español; si el idioma original ya coincide con el target, ambos campos son iguales). Esto cumple los dos requisitos por separado (transcripción del idioma original + traducción) sin duplicar la lógica de manejo de errores/timeouts — sigue siendo un solo call a Ollama por chunk. Si en producción la detección de idioma del modelo resulta poco confiable, la alternativa es correr un paso previo liviano de detección de idioma (ver `docs/SCALING.md` para más mejoras de Fase 2).
