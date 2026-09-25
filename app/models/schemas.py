from typing import Literal

from pydantic import BaseModel


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    seq: int
    lang: str
    original_text: str
    translated_text: str
    latency_s: float          # solo el tiempo de la llamada a Ollama
    audio_to_text_ms: int = 0  # demora real "de punta a punta": desde que se
                               # terminó de capturar el audio hasta que este
                               # texto quedó listo (incluye tiempo en cola +
                               # inferencia) — lo que de verdad percibe
                               # alguien hablando al micrófono
    ts: float


class RoomStatusEvent(BaseModel):
    type: Literal["status"] = "status"
    status: str
    detail: str | None = None
