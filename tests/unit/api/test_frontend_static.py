"""Regression tests for frontend static files served by the API."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

app_module = importlib.import_module("backend.api.app")


def test_favicon_is_served_as_svg(tmp_path, monkeypatch):
    """The browser favicon must return SVG content, not the SPA shell."""
    favicon = tmp_path / "favicon.svg"
    favicon.write_text('<svg xmlns="http://www.w3.org/2000/svg" />', encoding="utf-8")
    monkeypatch.setattr(app_module, "frontend_dist", tmp_path)

    client = TestClient(app_module.app)
    try:
        response = client.get("/favicon.svg")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.startswith("<svg")


def test_missing_favicon_returns_not_found(tmp_path, monkeypatch):
    """A missing favicon must not be mistaken for a valid SPA document."""
    monkeypatch.setattr(app_module, "frontend_dist", tmp_path)

    client = TestClient(app_module.app)
    try:
        response = client.get("/favicon.svg")
    finally:
        client.close()

    assert response.status_code == 404
