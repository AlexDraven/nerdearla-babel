from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BABEL_", env_file=".env")

    room_id: str = "main"

    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_api_key: str = "ollama"          # dummy, lo exige el cliente openai
    ollama_model: str = "gemma4:e2b"        # configurable a gemma4:e4b

    ingest_protocol: str = "rtmp"           # "rtmp" | "srt"
    ingest_host: str = "0.0.0.0"
    ingest_port: int = 1935
    sample_rate: int = 16000
    chunk_seconds: float = 4.0

    max_queue_size: int = 2
    concurrent_inference_workers: int = 1
    inference_timeout_seconds: float = 12.0
    ffmpeg_restart_backoff_seconds: float = 2.0

    glossary_path: str | None = None
    glossary_inline_threshold: int = 40

    log_level: str = "INFO"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
