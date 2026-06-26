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


def test_response_has_request_id_header(settings: Settings) -> None:
    with _client(settings) as client:
        resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")


def test_body_too_large_returns_413(settings: Settings) -> None:
    small = settings.model_copy(update={"max_request_body_size": 1024})
    app = create_app(small)
    with TestClient(app) as client:
        resp = client.post(
            "/eval",
            content=b'{"input": "' + b"x" * 4096 + b'"}',
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 413
    assert resp.headers.get("X-Request-ID")


def test_eval_rejects_total_upload_too_large(settings: Settings) -> None:
    capped = settings.model_copy(update={"max_total_upload_size": 4})
    with _client(capped) as client:
        resp = client.post(
            "/eval",
            json={
                "input": "pass",
                "files": [
                    {"path": "a.txt", "content": "aaa"},
                    {"path": "b.txt", "content": "bbb"},
                ],
            },
        )
    assert resp.status_code == 400
    assert "combined" in resp.json()["detail"]


def test_eval_returns_429_when_at_capacity(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"max_concurrent_evals": 1}))
    with TestClient(app) as client:
        # Exhaust the single slot directly so the next request is rejected.
        app.state.limiter._semaphore.acquire()
        try:
            resp = client.post("/eval", json={"input": "print(1)"})
        finally:
            app.state.limiter._semaphore.release()
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "1"
