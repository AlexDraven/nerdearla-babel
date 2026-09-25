from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BABEL_", env_file=".env")

    room_id: str = "main"
    room_ids: str = "main,room2,mic"  # CSV de salas a bootstrapear (ver app/rooms/bootstrap.py)
    mic_room_ids: str = "mic"         # ids que fuerzan protocol="mic" (ignora ingest_protocol global)
    ingest_base_port: int = 1935      # sala N escucha en ingest_base_port + N (no aplica a salas "mic")

    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_api_key: str = "ollama"          # dummy, lo exige el cliente openai
    ollama_model: str = "gemma4:e2b"        # configurable a gemma4:e4b

    ingest_protocol: str = "rtmp"           # "rtmp" | "srt" | "file" | "mic"
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 1935
    ingest_file_path: str | None = None     # usado cuando ingest_protocol == "file"
    ingest_loop: bool = True                # loopear el archivo en modo "file"
    demo_audio_dir: str = "tests/fixtures"  # convención: <demo_audio_dir>/<room_id>.wav
    sample_rate: int = 16000
    chunk_seconds: float = 4.0

    max_queue_size: int = 2
    concurrent_inference_workers: int = 1
    # RMS normalizado (0..1) por debajo del cual un chunk se descarta ANTES
    # de mandarlo a Ollama, sin llamar al modelo: gemma4:e2b, ante silencio o
    # solo ruido de piso (aire acondicionado, hum del mic), a veces devuelve
    # una frase inventada en vez de texto vacío — cortar acá por energía es
    # determinístico (no depende de que el modelo respete la instrucción del
    # prompt) y de paso ahorra la llamada. 0.015 (~-36dBFS) es conservador:
    # deja pasar voz baja, corta silencio/ruido de piso típico de un mic de
    # laptop. Si un mic específico tiene mucho ruido de fondo, subir este
    # valor (BABEL_SILENCE_RMS_THRESHOLD) hasta que deje de "escuchar" ruido.
    silence_rms_threshold: float = 0.015
    # 12s se quedaba corto ni bien hay 2+ salas compitiendo por el mismo
    # Ollama a la vez (medido real: gemma4:e2b tarda 6-46s por chunk según
    # carga, incluso con GPU) — con 12s TODOS los chunks terminaban en
    # timeout y no aparecía ninguna transcripción. Con margen real, se
    # pierden menos chunks a costa de un poco más de latencia percibida.
    inference_timeout_seconds: float = 30.0
    ffmpeg_restart_backoff_seconds: float = 2.0

    glossary_path: str | None = None
    glossary_dir: str = "glossaries"        # convención: <glossary_dir>/<room_id>.yaml; también
                                             # whitelist para el `path` de POST /rooms/{id}/glossary
    glossary_inline_threshold: int = 40

    log_level: str = "INFO"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
