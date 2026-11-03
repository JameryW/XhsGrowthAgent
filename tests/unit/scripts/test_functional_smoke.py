"""The deployment smoke script: classify PASS/FAIL/BLOCKED correctly.

The script is what an operator runs against a live process, so its judgements are
the contract: a deployment without an app DB must be reported as BLOCKED (valid
graph-only mode), while a 500 or a missing magpie provider is a FAIL.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import functional_smoke as smoke  # noqa: E402


def _response(status: int, payload=None, content_type: str = "application/json"):
    return smoke.HttpResponse(status, content_type, payload)


def _health_payload(*, magpie: bool = True, app_db: str = "ready"):
    providers = {"openai": {"configured": False}}
    if magpie:
        providers["magpie"] = {"configured": True}
    return {
        "success": True,
        "data": {
            "checks": {
                "llm_providers": {"status": "ok", "providers": providers},
                "database": {"status": "ok", "app_db": app_db},
            }
        },
    }


def test_health_fails_when_magpie_is_not_reported(monkeypatch):
    def fake(base_url, method, path, **kwargs):
        if path == "/health":
            return _response(200, {"success": True, "data": {}})
        return _response(200, _health_payload(magpie=False))

    monkeypatch.setattr(smoke, "_call", fake)

    results = smoke.check_health("http://test")
    by_name = {r.name: r for r in results}
    assert by_name["health llm_providers"].status == "FAIL"
    assert "magpie" in by_name["health llm_providers"].detail


def test_health_accepts_a_graph_only_deployment(monkeypatch):
    def fake(base_url, method, path, **kwargs):
        return _response(200, _health_payload(app_db="unavailable"))

    monkeypatch.setattr(smoke, "_call", fake)

    results = smoke.check_health("http://test")
    by_name = {r.name: r for r in results}
    assert by_name["health database"].status == "PASS"
    assert "graph-only" in by_name["health database"].detail


def test_public_checks_fail_on_a_missing_static_shell(monkeypatch):
    def fake(base_url, method, path, **kwargs):
        if path == "/":
            return _response(404, "not found", "text/plain")
        if path == "/api/public/showcase/cases":
            return _response(200, {"data": {"cases": []}})
        if path == "/api/public/showcase/cases/does-not-exist":
            return _response(404, {"error": {"code": "NOT_FOUND"}})
        return _response(401, {"error": {"code": "ERROR_AUTH_TOKEN_MISSING"}})

    monkeypatch.setattr(smoke, "_call", fake)

    results = smoke.check_public("http://test")
    by_name = {r.name: r for r in results}
    assert by_name["static shell /"].status == "FAIL"
    assert by_name["public showcase"].status == "PASS"
    assert by_name["public 404 handling"].status == "PASS"
    assert by_name["auth boundary"].status == "PASS"


def test_login_without_an_app_db_is_blocked_not_failed(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "_call",
        lambda *args, **kwargs: _response(
            503, {"error": {"code": smoke.DB_UNAVAILABLE_CODE, "message": "no db"}}
        ),
    )

    results = smoke.check_login(
        "http://test",
        username="admin",
        password="pw",
        start_workflow=False,
        account_id="acct",
    )
    assert [r.status for r in results] == ["BLOCKED"]
    assert "POSTGRES_URI" in results[0].detail


def test_login_failure_is_a_failure(monkeypatch):
    monkeypatch.setattr(
        smoke, "_call", lambda *args, **kwargs: _response(500, {"error": {"code": "X"}})
    )

    results = smoke.check_login(
        "http://test",
        username="admin",
        password="pw",
        start_workflow=False,
        account_id="acct",
    )
    assert results[0].status == "FAIL"


def test_main_returns_nonzero_only_for_failures(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "run_checks", lambda args: [smoke.Result("x", "PASS")])
    assert smoke.main(["--base-url", "http://test"]) == 0

    monkeypatch.setattr(smoke, "run_checks", lambda args: [smoke.Result("x", "BLOCKED", "no db")])
    assert smoke.main(["--base-url", "http://test"]) == 0

    monkeypatch.setattr(smoke, "run_checks", lambda args: [smoke.Result("x", "FAIL", "boom")])
    assert smoke.main(["--base-url", "http://test"]) == 1


def test_workflow_lifecycle_skips_when_start_fails(monkeypatch):
    def fake(base_url, method, path, **kwargs):
        return _response(422, {"error": {"code": "ERROR_VALIDATION"}})

    monkeypatch.setattr(smoke, "_call", fake)
    results = smoke._workflow_lifecycle("http://test", "token", "acct")
    assert [r.status for r in results] == ["FAIL"]
    assert "ERROR_VALIDATION" in results[0].detail


def _surface_responses(monkeypatch, *, asset_status: int = 200, unknown_route_json: bool = True):
    def fake(base_url, method, path, **kwargs):
        if path == "/openapi.json":
            return _response(200, {"paths": {"/health": {}}})
        if path == "/docs":
            return _response(200, "<html></html>", "text/html")
        if path == "/":
            return _response(
                200,
                '<html><script src="/assets/index.js"></script></html>',
                "text/html",
            )
        if path.startswith("/assets/"):
            return _response(asset_status, "asset", "text/javascript")
        if path == "/api/functional-smoke-does-not-exist":
            if unknown_route_json:
                return _response(
                    404, {"success": False, "error": {"code": "ERROR_ROUTE_NOT_FOUND"}}
                )
            return _response(404, "", "")
        if path == "/api/system/health" and method == "POST":
            return _response(405, {"detail": "Method Not Allowed"})
        if path == "/api/system/health":
            return smoke.HttpResponse(
                200, "application/json", {"success": True}, {"content-encoding": "gzip"}
            )
        if path == "/api/workflow/list" and method == "OPTIONS":
            return smoke.HttpResponse(200, "", {}, {"access-control-allow-origin": "*"})
        return _response(500, {"error": {"code": "X"}})

    monkeypatch.setattr(smoke, "_call", fake)


def test_surface_passes_on_a_healthy_instance(monkeypatch):
    _surface_responses(monkeypatch)
    results = smoke.check_deployment_surface("http://test")
    by_name = {r.name: r for r in results}
    assert all(r.status == "PASS" for r in results), by_name
    assert by_name["static assets"].detail == "1 assets"


def test_surface_fails_when_a_static_asset_is_missing(monkeypatch):
    _surface_responses(monkeypatch, asset_status=404)
    results = smoke.check_deployment_surface("http://test")
    by_name = {r.name: r for r in results}
    assert by_name["static assets"].status == "FAIL"
    assert "missing" in by_name["static assets"].detail


def test_surface_fails_when_unknown_api_route_is_not_an_envelope(monkeypatch):
    _surface_responses(monkeypatch, unknown_route_json=False)
    results = smoke.check_deployment_surface("http://test")
    by_name = {r.name: r for r in results}
    assert by_name["unknown api route"].status == "FAIL"
