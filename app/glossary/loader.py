from pathlib import Path

import yaml

from .models import Glossary


def load_glossary_from_yaml(path: str | Path) -> Glossary:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Glossary.model_validate(raw)
