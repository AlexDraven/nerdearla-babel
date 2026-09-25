from pathlib import Path

from app.glossary.loader import load_glossary_from_yaml

YAML_CONTENT = """
talk_title: "Charla de prueba"
speakers:
  - "Speaker Uno"
  - "Speaker Dos"
entries:
  - term: "Kubernetes"
    aliases: ["k8s"]
    core: true
  - term: "sidecar"
"""


def test_load_glossary_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "example.yaml"
    yaml_path.write_text(YAML_CONTENT, encoding="utf-8")

    glossary = load_glossary_from_yaml(yaml_path)

    assert glossary.talk_title == "Charla de prueba"
    assert glossary.speakers == ["Speaker Uno", "Speaker Dos"]
    assert len(glossary.entries) == 2

    kubernetes_entry = glossary.entries[0]
    assert kubernetes_entry.term == "Kubernetes"
    assert kubernetes_entry.aliases == ["k8s"]
    assert kubernetes_entry.core is True

    sidecar_entry = glossary.entries[1]
    assert sidecar_entry.core is False
    assert sidecar_entry.aliases == []


def test_load_empty_glossary(tmp_path: Path):
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text('talk_title: "Sin glosario"\n', encoding="utf-8")

    glossary = load_glossary_from_yaml(yaml_path)

    assert glossary.talk_title == "Sin glosario"
    assert glossary.entries == []
