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
   │                                    PCM -> WAV -> base64  ->  build_messages(glosario)
   │                                                                    ▼
   │                                    AsyncOpenAI(base_url=ollama).chat.completions.create(
   │                                        model, messages, response_format=json_object)
   │                                                                    ▼
   │                                    InferenceResult{lang, text_es, text_en}  (sanitize.py filtra
   │                                                                    │         caracteres fuera de es/en)
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
| `app/audio/transforms.py` | Envuelve PCM crudo en un WAV válido en memoria y lo codifica en base64. También `pcm_rms()`: RMS normalizado, gate de silencio antes de llamar a Ollama (ver `silence_rms_threshold` en `app/config.py`). |
| `app/glossary/` | Modelo y loader del glosario técnico por charla (YAML). |
| `app/inference/prompts.py` | Construye el prompt único: le da al modelo la certeza de que el audio siempre es español o inglés (nunca otro idioma), le pide devolver siempre los dos (`text_es`/`text_en`, transcripción fiel del que se habló + traducción del otro) y usar solo caracteres de esos dos idiomas — con el glosario inyectado. |
| `app/inference/sanitize.py` | `strip_non_latin_chars()`: filtro determinístico que saca cualquier carácter fuera de español/inglés de la respuesta del modelo — la regla del prompt de arriba no es 100% confiable por sí sola (un modelo chico puede meter texto de otro alfabeto igual). |
| `app/inference/ollama_client.py` | Cliente OpenAI-compatible contra Ollama — **nunca** usar `/api/chat` para audio. Manda `extra_body={"reasoning_effort": "none"}` en cada request: `gemma4:e2b` trae "thinking" activado por defecto en Ollama, que no se usa nunca y era la mayor parte del tiempo de generación (`think: false` nativo no se respeta en este endpoint; `reasoning_effort: "none"` sí) — desactivarlo bajó la demora audio→texto ~5-10x sin cambiar de hardware. |
| `app/inference/pipeline.py` | Consumer async: toma chunks de la cola, descarta los que están por debajo de `silence_rms_threshold` sin llamar al modelo, llama a Ollama, emite `TranscriptEvent` (con `text_es` y `text_en`). |
| `app/rooms/room.py` | Unidad de escalado: une ingesta + cola + pipeline + viewers de una sala. También acumula `transcript` (deque, cap 5000 eventos), expone `transcript_as_text()`, y en modo `mic` usa `_supervised_mic_loop`/`restart_mic_ingest()` en vez del loop de reintento genérico (ver más abajo). Las salas no-mic exponen `pause()`/`resume()` (control room → `POST /rooms/{id}/pause`\|`/resume`): cancelan/recrean la task de `_supervised_ingest_loop` en vez de solo cortar el ffmpeg, para que no haya ventana de carrera con el reintento automático por backoff (ver docstring de `pause()`). |
| `app/rooms/bootstrap.py` | Arma la lista de `Room` a partir de `BABEL_ROOM_IDS`, resolviendo el glosario y el audio de demo de cada una por convención de archivo, y forzando modo `mic` para los ids en `BABEL_MIC_ROOM_IDS`. |
| `app/ws/connection_manager.py` | Broadcast de eventos a los viewers WS conectados. |
| `app/main.py` | FastAPI: lifecycle de **todas** las `Room` (arrancan concurrentes), endpoints de control (`/rooms`, `/rooms/{id}/status`, `/transcript`, `/transcript.txt`, `/glossary`), WS de salida (`/ws/room/{id}`) y WS de entrada de micrófono (`/ws/mic/{id}`). CORS abierto para que el overlay/dashboard/mic (archivos estáticos, otro origen) puedan consumirlo. |
| `frontend/dashboard/` | Control room: pollea `GET /rooms` + abre un WS por sala para mostrar todas las sesiones activas en una sola pantalla (estado, cola, latencia, último subtítulo, link directo a grabar si es una sala `mic`). |
| `frontend/overlay/` | Dos modos sobre el mismo WS: `broadcast` (default, cartel efímero para OBS) y `?mode=reading` (scrollback + control de fuente/contraste + `aria-live`, para seguir la charla desde el propio dispositivo). |
| `frontend/mic/` | Captura el micrófono elegido por el usuario (`MediaRecorder`), lo manda a `/ws/mic/{id}` y muestra la transcripción en vivo en la misma página (WS de salida, igual que el overlay). |

## Rendimiento: por qué la demora bajó ~5-10x sin cambiar de hardware

Medido en esta Mac, mismo audio, antes/después de desactivar el "thinking" (`extra_body={"reasoning_effort": "none"}` en `ollama_client.py`, ver fila de arriba):

| Escenario | Demora audio→texto (antes) | Demora audio→texto (después) |
|---|---|---|
| 1 sala sola | ~15-20s | **~2-4s** |
| 2-3 salas compitiendo | 15-46s (algunos chunks se descartaban por timeout) | **~2-4s**, sin descartes por timeout |

Este cambio no depende del hardware — es gratis en cualquier GPU o incluso CPU. Ver [`DEPLOYMENT.md`](DEPLOYMENT.md#recomendación-de-hardware-para-escalar-a-más-salas) para cuánto más lejos se puede llevar esto con una GPU de datacenter.

## Decisión: un solo prompt, con salida dual (no dos pipelines)

En vez de mantener flujos separados para "transcripción" y "traducción", se usa un único prompt que le pide al modelo devolver **ambos** campos en la misma respuesta: `text_es` (siempre en español) y `text_en` (siempre en inglés) — uno es la transcripción fiel del idioma que efectivamente se habló, el otro la traducción. Esto cumple los dos requisitos por separado (transcripción del idioma original + traducción) sin duplicar la lógica de manejo de errores/timeouts — sigue siendo un solo call a Ollama por chunk. Si en producción la detección de idioma del modelo resulta poco confiable, la alternativa es correr un paso previo liviano de detección de idioma (ver `docs/SCALING.md` para más mejoras de Fase 2).

## Por qué el audio se asume siempre español o inglés

El prompt le da al modelo una certeza explícita en vez de dejarlo "adivinar" entre cualquier idioma: "el audio SIEMPRE está en español o en inglés". Sin esa restricción, un modelo multimodal chico (`gemma4:e2b`) ante audio ambiguo/ruidoso puede no solo elegir mal el idioma, sino directamente alucinar texto en un tercer alfabeto (cirílico, tailandés, etc.) — se observó en vivo (`"...se está hablando un poco..."` con caracteres tailandeses intercalados). Dos capas de defensa, no solo una:
1. **Prompt** (`app/inference/prompts.py`, regla 7): pedir explícitamente solo caracteres de español/inglés.
2. **Filtro determinístico** (`app/inference/sanitize.py:strip_non_latin_chars`), aplicado en `ollama_client.py` a cada respuesta: saca cualquier carácter fuera de ASCII + Latin-1 Supplement + Latin Extended-A + puntuación tipográfica común, sin depender de que el modelo respete la regla del prompt.
