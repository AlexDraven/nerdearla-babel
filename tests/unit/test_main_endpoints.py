"""Tests de los endpoints HTTP de app/main.py, usando httpx.ASGITransport
directo (NO fastapi.testclient.TestClient) para no disparar el `lifespan`
de la app real, que levantaría procesos ffmpeg de verdad."""

import httpx
import pytest

from app.config import Settings
from app.glossary.models import Glossary, GlossaryEntry
from app.main import app, room_manager
from app.models.schemas import TranscriptEvent
from app.rooms.room import Room


@pytest.fixture(autouse=True)
def _clean_room_manager():
    room_manager._rooms.clear()
    yield
    room_manager._rooms.clear()


def _register_room(room_id: str, glossary: Glossary | None = None) -> Room:
    room = Room(room_id=room_id, settings=Settings(ingest_protocol="rtmp"), glossary=glossary)
    room_manager.register(room)
    return room


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_rooms_empty():
    async with _client() as client:
        response = await client.get("/rooms")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_rooms_returns_registered_rooms():
    _register_room("main")
    _register_room("room2")

    async with _client() as client:
        response = await client.get("/rooms")

    body = response.json()
    assert {r["room_id"] for r in body} == {"main", "room2"}
    assert all({"status", "queue_size"} <= r.keys() for r in body)


@pytest.mark.parametrize(
    "path",
    ["/rooms/missing/status", "/rooms/missing/transcript", "/rooms/missing/transcript.txt", "/rooms/missing/glossary"],
)
async def test_room_not_found_returns_404(path):
    async with _client() as client:
        response = await client.get(path)

    assert response.status_code == 404


async def test_get_transcript_json_and_txt():
    room = _register_room("main")
    await room._emit_transcript(
        TranscriptEvent(seq=1, lang="es", original_text="hola", translated_text="hola", latency_s=0.1, ts=1_700_000_000.0)
    )

    async with _client() as client:
        json_resp = await client.get("/rooms/main/transcript")
        txt_resp = await client.get("/rooms/main/transcript.txt")

    assert json_resp.status_code == 200
    assert json_resp.json()["events"][0]["original_text"] == "hola"
    assert txt_resp.status_code == 200
    assert "(es) hola" in txt_resp.text


async def test_get_transcript_txt_empty_room():
    _register_room("main")

    async with _client() as client:
        response = await client.get("/rooms/main/transcript.txt")

    assert response.status_code == 200
    assert response.text == ""


async def test_get_glossary_returns_none_when_room_has_no_glossary():
    _register_room("main", glossary=None)

    async with _client() as client:
        response = await client.get("/rooms/main/glossary")

    assert response.status_code == 200
    assert response.json() == {"room_id": "main", "glossary": None}


async def test_get_glossary_returns_entries():
    glossary = Glossary(talk_title="Test", speakers=[], entries=[GlossaryEntry(term="Kubernetes")])
    _register_room("main", glossary=glossary)

    async with _client() as client:
        response = await client.get("/rooms/main/glossary")

    assert response.json()["glossary"]["talk_title"] == "Test"


async def test_cors_headers_present_for_cross_origin_request():
    _register_room("main")

    async with _client() as client:
        response = await client.get("/rooms", headers={"Origin": "http://example.com"})

    assert response.headers.get("access-control-allow-origin") == "*"


async def test_reload_glossary_rejects_path_traversal():
    _register_room("main")

    async with _client() as client:
        response = await client.post("/rooms/main/glossary", params={"path": "../../../etc/passwd"})

    assert response.status_code == 400


async def test_reload_glossary_rejects_absolute_path():
    _register_room("main")

    async with _client() as client:
        response = await client.post("/rooms/main/glossary", params={"path": "/etc/passwd"})

    assert response.status_code == 400


async def test_reload_glossary_rejects_malformed_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "glossaries").mkdir()
    (tmp_path / "glossaries" / "broken.yaml").write_text("talk_title: [unclosed", encoding="utf-8")
    _register_room("main")

    async with _client() as client:
        response = await client.post("/rooms/main/glossary", params={"path": "broken.yaml"})

    assert response.status_code == 400


async def test_reload_glossary_accepts_valid_path_within_glossary_dir():
    _register_room("main")

    async with _client() as client:
        response = await client.post("/rooms/main/glossary", params={"path": "example-charla-kubernetes.yaml"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["terms"] > 0
