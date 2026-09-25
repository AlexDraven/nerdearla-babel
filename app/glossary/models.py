from pydantic import BaseModel


class GlossaryEntry(BaseModel):
    term: str
    aliases: list[str] = []
    note: str | None = None
    core: bool = False  # siempre se incluye, aunque el glosario sea grande


class Glossary(BaseModel):
    talk_title: str
    speakers: list[str] = []
    entries: list[GlossaryEntry] = []
