"""Router-level errors keep the ApiResponse contract for /api/* paths.

FastAPI's default 404 for an unmatched API route is an empty body with no
Content-Type; the frontend then reports a network error and hides proxy/base-path
mistakes.  These tests pin the envelope and make sure the change did not swallow
405 or the non-API default shape.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

app_module = importlib.import_module("backend.api.app")


def _client() -> TestClient:
    return TestClient(app_module.app)


def test_unknown_api_route_returns_the_error_envelope():
    client = _client()
    try:
        response = client.get("/api/functional-smoke-does-not-exist")
    finally:
        client.close()

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "ERROR_ROUTE_NOT_FOUND"
    assert "No API route matches" in body["error"]["message"]


def test_wrong_method_still_returns_405():
    client = _client()
    try:
        response = client.post("/api/system/health")
    finally:
        client.close()

    assert response.status_code == 405


def test_non_api_404_keeps_the_default_shape():
    client = _client()
    try:
        response = client.get("/assets/does-not-exist.js")
    finally:
        client.close()

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert "success" not in body
