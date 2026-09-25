# Arquitectura

Ver [`PLAN.md`](../PLAN.md) para el diseño completo con snippets de código. Este documento resume el flujo de datos para referencia rápida.

```
OBS/consola  ──RTMP/SRT──▶  FFmpeg (subprocess, -listen 1)  ──PCM s16le stdout──▶
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
   │                                              InferenceResult{lang, text}
   │                                                                    ▼
Viewers ◀── WS broadcast (ConnectionManager) ◀── TranscriptEvent
```

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `app/audio/ffmpeg_ingest.py` | Levanta y supervisa el subprocess FFmpeg que hace de servidor RTMP/SRT y entrega PCM en chunks de tamaño exacto. |
| `app/audio/transforms.py` | Envuelve PCM crudo en un WAV válido en memoria y lo codifica en base64. |
| `app/glossary/` | Modelo y loader del glosario técnico por charla (YAML). |
| `app/inference/prompts.py` | Construye el prompt único (detección de idioma + transcripción/traducción) con el glosario inyectado. |
| `app/inference/ollama_client.py` | Cliente OpenAI-compatible contra Ollama — **nunca** usar `/api/chat` para audio. |
| `app/inference/pipeline.py` | Consumer async: toma chunks de la cola, llama a Ollama, emite `TranscriptEvent`. |
| `app/rooms/room.py` | Unidad de escalado: une ingesta + cola + pipeline + viewers de una sala. |
| `app/ws/connection_manager.py` | Broadcast de eventos a los viewers WS conectados. |
| `app/main.py` | FastAPI: lifecycle de la `Room`, endpoints de control y WS de salida. |

## Decisión: un solo prompt, no dos pipelines

En vez de mantener flujos separados para "transcripción ES→ES" y "traducción EN→ES", se usa un único prompt que le pide al modelo detectar el idioma y actuar en consecuencia, devolviendo siempre español. Esto simplifica el manejo de errores y timeouts (un solo call por chunk) a costa de depender de que el modelo detecte el idioma correctamente — si en producción esto resulta poco confiable, la alternativa es correr detección de idioma como paso previo liviano (ver `docs/SCALING.md` para más mejoras de Fase 2).
