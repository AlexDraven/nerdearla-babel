from pathlib import Path

import yaml

from .models import Glossary


def resolve_within(base_dir: str | Path, filename: str) -> Path:
    """Resuelve `filename` dentro de `base_dir`, rechazando cualquier intento
    de escapar el directorio (path traversal vía `..` o una ruta absoluta).
    Usar siempre que `filename` pueda venir de un cliente de red (ver
    POST /rooms/{id}/glossary en app/main.py) — para paths de confianza
    fijados por el operador (ej. BABEL_GLOSSARY_PATH) no hace falta."""
    base = Path(base_dir).resolve()
    candidate = (base / filename).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"'{filename}' resuelve fuera de '{base_dir}'")
    return candidate


def load_glossary_from_yaml(path: str | Path) -> Glossary:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Glossary.model_validate(raw)
