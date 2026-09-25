from typing import Literal

from pydantic import BaseModel


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    seq: int
    lang: str
    text: str
    latency_s: float


class RoomStatusEvent(BaseModel):
    type: Literal["status"] = "status"
    status: str
    detail: str | None = None
