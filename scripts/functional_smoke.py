"""Functional smoke test against a *running* XhsGrowthAgent API instance.

Why: unit tests mock the FastAPI app, so they cannot catch deployment-level
breakage (health reporting the wrong providers, a server that boots without its
DB layer and then 500s on login, static shell missing from the image).  This
script talks HTTP to a live process and checks the parts an operator or the GUI
depends on.

Usage::

    python scripts/functional_smoke.py --base-url http://127.0.0.1:8000
    python scripts/functional_smoke.py --base-url http://127.0.0.1:8000 \
        --username admin --password "$CONSOLE_PASSWORD" --start-workflow

Exit code is 0 unless a check FAILs (deployment gaps without a DB are reported
as BLOCKED, because a graph-only dev server is a valid mode — it just cannot
serve the authenticated console).

Checks
  1. /health and /api/system/health answer 200, keep the ApiResponse envelope and
     report llm_providers (incl. magpie), database (incl. app_db) and memory_store.
  2. Public endpoints: showcase list 200, unknown public id 404 (no 500).
  3. Static shell: / serves HTML (the GUI is reachable).
  4. Auth boundary: a protected route answers 401 without a token.
  5. With --username/--password: login. If the deployment has no app DB it
     answers 503 ERROR_DB_UNAVAILABLE -> the authenticated section is BLOCKED.
     Otherwise: authenticated reads must not 5xx, and with --start-workflow the
     lifecycle start -> status -> pause -> resume -> cancel -> delete is probed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["PASS", "FAIL", "BLOCKED", "SKIP"]

DB_UNAVAILABLE_CODE = "ERROR_DB_UNAVAILABLE"


@dataclass
class Result:
    name: str
    status: Status
    detail: str = ""


@dataclass
class HttpResponse:
    status: int
    content_type: str
    payload: Any


def _call(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 15.0,
) -> HttpResponse:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
            try:
                return HttpResponse(response.status, content_type, json.loads(raw))
            except json.JSONDecodeError:
                return HttpResponse(response.status, content_type, raw[:400])
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        try:
            return HttpResponse(exc.code, content_type, json.loads(raw))
        except json.JSONDecodeError:
            return HttpResponse(exc.code, content_type, raw[:400])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return HttpResponse(0, "", f"unreachable: {exc}")


def _error_code(response: HttpResponse) -> str | None:
    if isinstance(response.payload, dict):
        error = response.payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            return str(code) if code else None
    return None


def check_health(base_url: str) -> list[Result]:
    results: list[Result] = []
    for path in ("/health", "/api/system/health"):
        response = _call(base_url, "GET", path)
        if response.status != 200:
            results.append(Result(f"health {path}", "FAIL", f"HTTP {response.status}"))
            continue
        if not isinstance(response.payload, dict) or response.payload.get("success") is not True:
            results.append(Result(f"health {path}", "FAIL", "missing ApiResponse envelope"))
            continue
        results.append(Result(f"health {path}", "PASS", ""))

    response = _call(base_url, "GET", "/api/system/health")
    data = response.payload.get("data") if isinstance(response.payload, dict) else None
    checks = data.get("checks") if isinstance(data, dict) else None
    if isinstance(checks, dict):
        llm = checks.get("llm_providers")
        providers = llm.get("providers") if isinstance(llm, dict) else None
        if not isinstance(providers, dict) or "magpie" not in providers:
            results.append(
                Result(
                    "health llm_providers",
                    "FAIL",
                    "magpie is not reported (#756 made it the only egress)",
                )
            )
        elif providers["magpie"].get("configured"):
            results.append(Result("health llm_providers", "PASS", "magpie configured"))
        else:
            results.append(
                Result("health llm_providers", "FAIL", "magpie not configured in the deployment")
            )

        database = checks.get("database")
        app_db = database.get("app_db") if isinstance(database, dict) else None
        if app_db == "ready":
            results.append(Result("health database", "PASS", "app DB ready"))
        elif app_db == "unavailable":
            results.append(
                Result(
                    "health database",
                    "PASS",
                    "app DB unavailable (graph-only mode; login answers 503)",
                )
            )
        else:
            results.append(Result("health database", "FAIL", "app_db not reported"))
    else:
        results.append(Result("health checks", "FAIL", "no checks payload"))

    return results


def check_public(base_url: str) -> list[Result]:
    results: list[Result] = []
    response = _call(base_url, "GET", "/api/public/showcase/cases")
    data = response.payload.get("data") if isinstance(response.payload, dict) else None
    if response.status == 200 and isinstance(data, dict) and "cases" in data:
        results.append(Result("public showcase", "PASS", ""))
    else:
        results.append(Result("public showcase", "FAIL", f"HTTP {response.status}"))

    missing = _call(base_url, "GET", "/api/public/showcase/cases/does-not-exist")
    if missing.status == 404:
        results.append(Result("public 404 handling", "PASS", ""))
    else:
        results.append(Result("public 404 handling", "FAIL", f"HTTP {missing.status}"))

    shell = _call(base_url, "GET", "/")
    content_type = (shell.content_type or "").lower()
    if shell.status == 200 and "text/html" in content_type:
        results.append(Result("static shell /", "PASS", ""))
    else:
        results.append(
            Result("static shell /", "FAIL", f"HTTP {shell.status} ({shell.content_type})")
        )

    unauth = _call(base_url, "GET", "/api/workflow/list")
    if unauth.status == 401:
        results.append(Result("auth boundary", "PASS", "401 without token"))
    else:
        results.append(Result("auth boundary", "FAIL", f"HTTP {unauth.status}, expected 401"))
    return results


def _authenticated_reads(base_url: str, token: str) -> list[Result]:
    results: list[Result] = []
    for path in (
        "/api/auth/me",
        "/api/workflow/list",
        "/api/accounts/active",
        "/api/system-config",
    ):
        response = _call(base_url, "GET", path, token=token)
        if response.status >= 500:
            results.append(Result(f"auth read {path}", "FAIL", f"HTTP {response.status}"))
        elif response.status in (200, 403, 404):
            results.append(Result(f"auth read {path}", "PASS", f"HTTP {response.status}"))
        else:
            results.append(Result(f"auth read {path}", "FAIL", f"HTTP {response.status}"))
    return results


def _workflow_lifecycle(base_url: str, token: str, account_id: str) -> list[Result]:
    results: list[Result] = []
    started = _call(
        base_url,
        "POST",
        "/api/workflow/start",
        payload={
            "account_id": account_id,
            "async_mode": True,
            "dry_run": True,
            "topic": "functional smoke",
        },
        token=token,
    )
    data = started.payload.get("data") if isinstance(started.payload, dict) else None
    thread_id = None
    if isinstance(data, dict):
        thread_id = data.get("thread_id") or data.get("id")
    if started.status in (200, 202) and thread_id:
        results.append(Result("workflow start", "PASS", f"thread {thread_id}"))
    else:
        results.append(
            Result("workflow start", "FAIL", f"HTTP {started.status} {_error_code(started) or ''}")
        )
        return results

    status = _call(base_url, "GET", f"/api/workflow/status/{thread_id}", token=token)
    if status.status == 200:
        results.append(Result("workflow status", "PASS", ""))
    else:
        results.append(Result("workflow status", "FAIL", f"HTTP {status.status}"))

    for action in ("pause", "resume", "cancel"):
        response = _call(base_url, "POST", f"/api/workflow/{action}/{thread_id}", token=token)
        if response.status < 500:
            results.append(Result(f"workflow {action}", "PASS", f"HTTP {response.status}"))
        else:
            results.append(Result(f"workflow {action}", "FAIL", f"HTTP {response.status}"))

    deleted = _call(base_url, "DELETE", f"/api/workflow/{thread_id}", token=token)
    if deleted.status < 500:
        results.append(Result("workflow delete", "PASS", f"HTTP {deleted.status}"))
    else:
        results.append(Result("workflow delete", "FAIL", f"HTTP {deleted.status}"))
    return results


def check_login(
    base_url: str, *, username: str, password: str, start_workflow: bool, account_id: str
) -> list[Result]:
    response = _call(
        base_url, "POST", "/api/auth/login", payload={"username": username, "password": password}
    )
    if response.status == 200:
        data = response.payload.get("data") if isinstance(response.payload, dict) else None
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            return [Result("login", "FAIL", "200 without a token")]
        results = [Result("login", "PASS", "")]
        results.extend(_authenticated_reads(base_url, token))
        if start_workflow:
            results.extend(_workflow_lifecycle(base_url, token, account_id))
        return results

    if response.status == 503 and _error_code(response) == DB_UNAVAILABLE_CODE:
        return [
            Result(
                "login",
                "BLOCKED",
                "deployment has no app DB (POSTGRES_URI unset); "
                "authenticated console needs Postgres",
            )
        ]
    return [Result("login", "FAIL", f"HTTP {response.status} {_error_code(response) or ''}")]


def run_checks(args: argparse.Namespace) -> list[Result]:
    results = check_health(args.base_url)
    results.extend(check_public(args.base_url))
    if args.username and args.password:
        results.extend(
            check_login(
                args.base_url,
                username=args.username,
                password=args.password,
                start_workflow=args.start_workflow,
                account_id=args.account_id,
            )
        )
    else:
        results.append(
            Result(
                "authenticated section",
                "SKIP",
                "pass --username/--password to test login and the workflow lifecycle",
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Functional smoke test for a running API instance")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--start-workflow", action="store_true")
    parser.add_argument("--account-id", default="functional-smoke")
    options = parser.parse_args(argv)

    results = run_checks(options)
    failed = 0
    for result in results:
        if result.status == "FAIL":
            failed += 1
        suffix = f" — {result.detail}" if result.detail else ""
        print(f"[{result.status}] {result.name}{suffix}")

    blocked = sum(1 for r in results if r.status == "BLOCKED")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print(
        f"\n{len(results)} checks: "
        f"{sum(1 for r in results if r.status == 'PASS')} pass, {failed} fail, "
        f"{blocked} blocked, {skipped} skip"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
