"""End-to-end API tests using the fake NsJail and FastAPI's test client."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from aisnekbox.api.app import create_app
from aisnekbox.config import Settings


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_eval_success(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.post("/eval", json={"input": "print(2 + 2)"})
    assert resp.status_code == 200
    body = resp.json()
    assert "4" in body["stdout"]
    assert body["returncode"] == 0
    assert body["files"] == []


def test_eval_returns_files(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.post("/eval", json={"input": "open('r.txt','w').write('hi')"})
    body = resp.json()
    assert len(body["files"]) == 1
    assert base64.b64decode(body["files"][0]["content"]) == b"hi"


def test_eval_rejects_disallowed_executable(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.post("/eval", json={"input": "print(1)", "executable_path": "/bin/sh"})
    assert resp.status_code == 400
    assert "not permitted" in resp.json()["detail"]


def test_eval_rejects_path_traversal(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.post(
            "/eval",
            json={"input": "pass", "files": [{"path": "../x", "content": "y"}]},
        )
    assert resp.status_code == 422


def test_eval_requires_input(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.post("/eval", json={})
    assert resp.status_code == 422
