"""``json_object_body`` must treat absent/invalid JSON bodies as ``{}``.

Regression: sending ``Content-Type: application/json`` with an empty body made
``request.json()`` raise ``JSONDecodeError`` → unhandled 500 on the workflow
resume/retry endpoints that accept an optional body.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.body import json_object_body


def _client() -> TestClient:
    app = FastAPI()

    @app.post("/probe")
    async def probe(request: Request) -> dict:
        return await json_object_body(request)

    return TestClient(app)


def test_empty_body_with_json_content_type_is_empty_dict():
    response = _client().post("/probe", headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json() == {}


def test_malformed_json_is_empty_dict():
    response = _client().post(
        "/probe",
        headers={"Content-Type": "application/json"},
        content=b"{not-json",
    )
    assert response.status_code == 200
    assert response.json() == {}


def test_non_object_json_is_empty_dict():
    response = _client().post("/probe", json=["a", "b"])
    assert response.status_code == 200
    assert response.json() == {}


def test_valid_object_passes_through():
    response = _client().post("/probe", json={"force": True})
    assert response.status_code == 200
    assert response.json() == {"force": True}


def test_non_json_content_type_is_empty_dict():
    response = _client().post(
        "/probe", headers={"Content-Type": "text/plain"}, content=b"force=true"
    )
    assert response.status_code == 200
    assert response.json() == {}
