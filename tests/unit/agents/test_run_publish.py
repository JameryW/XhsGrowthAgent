"""Tests for run_publish — the extracted real-publish core (used by publish-retry).

Locks that: (1) extraction from PublisherAgent.execute preserved behavior,
(2) run_publish NEVER honors dry_run (retry always means real publish),
(3) account CDP endpoint resolution, (4) missing-CDP fast-fail with structured recovery,
(5) auth error classification, (6) history recording gated on post_id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.publisher import _resolve_cdp_endpoint, run_publish


def _state(**overrides):
    base = {
        "copy_content": {"selected_title": "t", "body_text": "b", "hashtags": []},
        "content_plan": {},
        "visual_plan": {"image_paths": ["/tmp/x.png"]},
        "account_id": "test_account",
        "session_id": "test_session",
        "publish_options": {"dry_run": False},
    }
    base.update(overrides)
    return base


@pytest.fixture
def _browser_settings(monkeypatch):
    """Force use_browser=True, dry_run=False so the real-publish branch runs."""
    fake = MagicMock()
    fake.platform.use_browser = True
    fake.platform.headless = True
    fake.platform.cdp_endpoint = ""
    monkeypatch.setattr("backend.config.settings.Settings", lambda: fake)
    return fake


def _mock_client(post_id="p1"):
    client = MagicMock()
    client.publish_post = AsyncMock(
        return_value={
            "post_id": post_id,
            "post_url": "u",
            "status": "published",
            "published_at": "now",
        }
    )
    client.close = AsyncMock()
    return client


def _patch_client(monkeypatch, client):
    ctor = MagicMock(side_effect=lambda **kw: client)
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", ctor)
    return ctor


def test_resolve_cdp_endpoint_uses_env_when_settings_attr_missing(monkeypatch):
    class Platform:
        pass

    class RuntimeSettings:
        platform = Platform()

    monkeypatch.setenv("XHS_CDP_ENDPOINT", "http://cdp.example:9222")

    assert _resolve_cdp_endpoint(RuntimeSettings()) == "http://cdp.example:9222"


def _mock_history(monkeypatch):
    hist = MagicMock()
    hist.return_value.record = AsyncMock()
    monkeypatch.setattr("backend.memory.content_history.ContentHistory", hist)
    return hist


def _mock_account_active(monkeypatch, is_active=True):
    """Patch get_account so the is_active pre-publish check doesn't hit the DB pool."""
    from backend.db.accounts import AccountRow

    account = AccountRow(id="acc", name="acc", is_active=is_active)
    monkeypatch.setattr("backend.db.accounts.get_account", AsyncMock(return_value=account))
    return account


def _mock_cdp_endpoint(monkeypatch, endpoint=""):
    """Patch get_account_cdp_endpoint so per-account CDP resolution doesn't hit the DB."""
    monkeypatch.setattr(
        "backend.db.accounts.get_account_cdp_endpoint", AsyncMock(return_value=endpoint)
    )


@pytest.mark.asyncio
async def test_uses_selected_account_cdp_profile(_browser_settings, mock_store, monkeypatch):
    """account_id in publish_options → per-account CDP endpoint passed to XHSClient."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9225")
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == ""
    assert kwargs["user_id"] == ""
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9225"
    assert result["publish_result"]["post_id"] == "p1"


@pytest.mark.asyncio
async def test_falls_back_to_global_when_no_account(_browser_settings, mock_store, monkeypatch):
    """No account_id → use global CDP endpoint."""
    state = _state(publish_options={"dry_run": False})
    client = _mock_client("p2")
    monkeypatch.setattr(
        "backend.agents.publisher._resolve_cdp_endpoint", lambda _s: "http://global:9223"
    )
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == ""
    assert kwargs["user_id"] == ""
    assert kwargs["cdp_endpoint"] == "http://global:9223"


@pytest.mark.asyncio
async def test_per_account_cdp_endpoint_passed_to_client(
    _browser_settings, mock_store, monkeypatch
):
    """Selected account with a cdp_port → per-account endpoint passed to XHSClient,
    overriding the global _resolve_cdp_endpoint result."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    kwargs = m_client.call_args.kwargs
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9223"


@pytest.mark.asyncio
async def test_per_account_empty_endpoint_falls_back_to_global(
    _browser_settings, mock_store, monkeypatch
):
    """Selected account with no cdp_port binding → global endpoint is used."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")  # account has no port binding
    # Make the global resolver return a known value so we can assert the fallback.
    monkeypatch.setattr(
        "backend.agents.publisher._resolve_cdp_endpoint", lambda _s: "http://global:9223"
    )
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    kwargs = m_client.call_args.kwargs
    assert kwargs["cdp_endpoint"] == "http://global:9223"


@pytest.mark.asyncio
async def test_missing_cdp_endpoint_returns_failed(_browser_settings, mock_store, monkeypatch):
    """Selected account without CDP endpoint → fail fast, no XHSClient built."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_empty"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")  # no per-account CDP profile
    monkeypatch.setattr(
        "backend.agents.publisher._resolve_cdp_endpoint",
        lambda _s: "",  # no global CDP either
    )
    m_client = MagicMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", m_client)

    result = await run_publish(state, store=mock_store)

    m_client.assert_not_called()
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "missing_cdp_endpoint"
    rec = pr["recovery"]
    assert isinstance(rec, dict)
    assert rec["action"] == "reconfigure"


@pytest.mark.asyncio
async def test_cdp_endpoint_proceeds_with_empty_cookie(_browser_settings, mock_store, monkeypatch):
    """CDP endpoint present → proceed with empty cookie/user_id."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_cdp"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_cdp")
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == ""
    assert kwargs["user_id"] == ""
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9223"
    assert result["publish_result"]["post_id"] == "p_cdp"


@pytest.mark.asyncio
async def test_classifies_auth_error(_browser_settings, mock_store, monkeypatch):
    """publish throws auth error → auth_expired error_type + structured recovery."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")

    client = MagicMock()
    client.publish_post = AsyncMock(side_effect=RuntimeError("cookie expired, login required"))
    client.close = AsyncMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", lambda **kw: client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "auth_expired"
    assert isinstance(pr["recovery"], dict)


@pytest.mark.asyncio
async def test_preserves_publish_service_error(_browser_settings, mock_store, monkeypatch):
    """publish_post returning a platform error keeps error/recovery in state."""

    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")

    client = MagicMock()
    client.publish_post = AsyncMock(
        return_value={"post_id": "", "status": "failed", "error": "未绑定手机号"}
    )
    client.close = AsyncMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", lambda **kw: client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error"] == "未绑定手机号"
    assert pr["error_type"] == "account_unverified"
    assert pr["recovery"]["action"] == "verify_account"


@pytest.mark.asyncio
async def test_never_honors_dry_run(_browser_settings, mock_store, monkeypatch):
    """run_publish ignores dry_run=True — retry always means real publish.

    This is the contract that justifies the extraction: execute's mock branch
    must NOT be reachable from the retry path.
    """
    state = _state(publish_options={"dry_run": True, "account_id": "acc_1"})
    client = _mock_client("p_real")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    # Real publish ran (publish_post awaited), not the mock path
    client.publish_post.assert_awaited_once()
    assert result["publish_result"]["post_id"] == "p_real"
    assert result["publish_result"]["status"] != "mock_published"


@pytest.mark.asyncio
async def test_records_history_on_success_only(_browser_settings, mock_store, monkeypatch):
    """ContentHistory.record called on success (post_id present), skipped on failure."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p_ok")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, client)
    hist = _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    hist.return_value.record.assert_awaited_once()
    data = hist.return_value.record.await_args.kwargs["data"]
    assert data["title"] == "t"

    # Now a failed publish (empty post_id) → record NOT called
    client_fail = MagicMock()
    client_fail.publish_post = AsyncMock(return_value={"post_id": "", "status": "failed"})
    client_fail.close = AsyncMock()
    _patch_client(monkeypatch, client_fail)
    hist.return_value.record.reset_mock()

    await run_publish(state, store=mock_store)

    hist.return_value.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_records_history_when_published_without_post_id(
    _browser_settings, mock_store, monkeypatch
):
    """Real XHS publish redirects to /publish/success — post_id regex-miss → empty.

    status=="published" must still record to ContentHistory (was skipped when
    gate was post_id-only). Regression for the same bug class as PR #190.
    """
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    # post_id="" but status="published" — real-world success shape
    client = _mock_client(post_id="")
    client.publish_post = AsyncMock(
        return_value={
            "post_id": "",
            "post_url": "https://creator.xiaohongshu.com/publish/success",
            "status": "published",
            "published_at": "now",
        }
    )
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, client)
    hist = _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    hist.return_value.record.assert_awaited_once()
    assert hist.return_value.record.await_args.kwargs["post_id"] == ""


@pytest.mark.asyncio
async def test_ignores_past_suggested_timing(_browser_settings, mock_store, monkeypatch):
    """Historical plan suggestions must not turn a real retry into scheduled publish."""

    state = _state(content_plan={"suggested_timing": "2023-10-29T20:30:00Z"})
    client = _mock_client("p_sched")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    post = client.publish_post.await_args.args[0]
    assert post.scheduled_time == ""


# ── P0-W4: idempotency key + failed-vs-unknown separation ─────────────────────


def _real_store():
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


@pytest.mark.asyncio
async def test_timeout_after_submit_action_marks_unknown_not_failed(_browser_settings, monkeypatch):
    """A browser/HTTP timeout during the real submit action means the note may
    have been published anyway — status must be "unknown", never "failed"
    (a false "failed" invites a duplicate publish)."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_t"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")

    client = MagicMock()
    client.publish_post = AsyncMock(side_effect=TimeoutError("page load timed out"))
    client.close = AsyncMock()
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=_real_store())

    pr = result["publish_result"]
    assert pr["status"] == "unknown"
    assert isinstance(pr["recovery"], dict)  # spec: recovery must stay a dict
    assert "publish_post" in str(pr["error"]) or "timed out" in str(pr["error"])


@pytest.mark.asyncio
async def test_non_timeout_error_still_marks_failed(_browser_settings, monkeypatch):
    """Non-timeout submit errors keep the old "failed" classification."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_f"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = MagicMock()
    client.publish_post = AsyncMock(side_effect=RuntimeError("boom"))
    client.close = AsyncMock()
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=_real_store())
    assert result["publish_result"]["status"] == "failed"


@pytest.mark.asyncio
async def test_second_real_publish_of_same_content_blocked(_browser_settings, monkeypatch):
    """After a successful real publish, a second real publish of the same
    (account, content, window) must be blocked before touching the client."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_d"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_once")
    ctor = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)
    store = _real_store()

    first = await run_publish(state, store=store)
    assert first["publish_result"]["status"] == "published"

    second = await run_publish(state, store=store)

    assert second["publish_result"]["status"] == "failed"
    assert second["publish_result"]["error_type"] == "duplicate_publish_blocked"
    assert isinstance(second["publish_result"]["recovery"], dict)
    # publish_post only ran for the first attempt (one client construction).
    client.publish_post.assert_awaited_once()
    assert ctor.call_count == 1


@pytest.mark.asyncio
async def test_unknown_record_blocks_second_publish(_browser_settings, monkeypatch):
    """A pre-existing "unknown" idempotency record blocks the next real publish."""
    from backend.agents.publisher import PUBLISH_IDEMPOTENCY_NS, compute_publish_id

    state = _state(publish_options={"dry_run": False, "account_id": "acc_u"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(PUBLISH_IDEMPOTENCY_NS, pid, {"status": "unknown", "publish_id": pid})

    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_never")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=store)
    assert result["publish_result"]["error_type"] == "duplicate_publish_blocked"
    client.publish_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_publish_bypasses_idempotency_guard(_browser_settings, monkeypatch):
    """Explicit force (publish-retry force=true path) overrides the duplicate
    block while still recording the attempt."""
    from backend.agents.publisher import PUBLISH_IDEMPOTENCY_NS, compute_publish_id

    state = _state(
        publish_options={"dry_run": False, "account_id": "acc_forced", "force_publish": True}
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(PUBLISH_IDEMPOTENCY_NS, pid, {"status": "unknown", "publish_id": pid})

    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_forced")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=store)
    assert result["publish_result"]["post_id"] == "p_forced"
    client.publish_post.assert_awaited_once()


def test_publish_id_is_deterministic_within_window():
    """Same account+content+images inside the window ⇒ same publish_id."""
    from backend.agents.publisher import compute_publish_id

    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    a = compute_publish_id(state)
    b = compute_publish_id(dict(state))
    assert a and a == b

    # Different account or different content ⇒ different key.
    other_acct = _state(publish_options={"dry_run": False, "account_id": "acc_2"})
    assert compute_publish_id(other_acct) != a
    other_content = _state(
        copy_content={"selected_title": "完全不同", "body_text": "x", "hashtags": []},
        publish_options={"dry_run": False, "account_id": "acc_1"},
    )
    assert compute_publish_id(other_content) != a


@pytest.mark.asyncio
async def test_dry_run_top_level_guard_is_never_bypassed(monkeypatch):
    """Dry-run double protection anchor: state["dry_run"]=True with
    publish_options.dry_run=False must still take the mock path (top-level
    workflow contract beats per-decision flag)."""
    from backend.agents.publisher import PublisherAgent

    fake = MagicMock()
    fake.platform.use_browser = True
    fake.platform.cdp_endpoint = ""
    monkeypatch.setattr("backend.config.settings.Settings", lambda: fake)
    client = MagicMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", client)

    state = {
        "session_id": "s",
        "account_id": "a",
        "dry_run": True,  # workflow-level dry_run
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "visual_plan": {},
        "content_plan": {},
        "publish_options": {"dry_run": False},  # user tries to flip it
    }
    result = await PublisherAgent().execute(state, store=AsyncMock())

    client.assert_not_called()
    assert result["publish_result"]["status"] == "mock_published"


# ── P0-W4: publish-retry "unknown" protection (service layer) ─────────────────


@pytest.mark.asyncio
async def test_reconcile_unknown_publish_finds_confirmed_record():
    """An idempotency record upgraded to published reconciles the unknown."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS, pid, {"status": "published", "publish_id": pid, "post_id": "pp"}
    )

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "published"


@pytest.mark.asyncio
async def test_reconcile_unknown_publish_finds_history_match():
    """A matching published entry in content history reconciles the unknown."""
    from backend.agents.publisher import reconcile_unknown_publish
    from backend.memory.store import MemoryManager

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r2"})
    store = _real_store()
    mm = MemoryManager("acc_r2")
    await store.aput(
        mm.content_history_ns,
        "note-1",
        {"title": "t", "status": "published", "post_id": "note-1"},
    )

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "published"


@pytest.mark.asyncio
async def test_reconcile_unknown_publish_uncertain_without_evidence():
    from backend.agents.publisher import reconcile_unknown_publish

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r3"})
    recon = await reconcile_unknown_publish(state, _real_store())
    assert recon["status"] == "uncertain"


def test_unknown_retry_requires_force_gate():
    """Endpoint gate: unknown + no force + uncertain reconciliation must be
    rejected (early response), never silently re-publish."""
    from backend.agents.publisher import evaluate_unknown_publish_retry

    gate = evaluate_unknown_publish_retry(
        pr_status="unknown", force=False, reconciled={"status": "uncertain"}
    )
    assert gate is not None
    assert gate["status"] == "requires_force"

    # force=true proceeds (returns None → caller continues the retry).
    assert evaluate_unknown_publish_retry("unknown", True, {"status": "uncertain"}) is None
    # reconciliation confirming publication short-circuits with reconciled.
    done = evaluate_unknown_publish_retry(
        "unknown", False, {"status": "published", "evidence": {"post_id": "x"}}
    )
    assert done is not None and done["status"] == "reconciled"
    # non-unknown statuses are unaffected.
    assert evaluate_unknown_publish_retry("failed", False, {"status": "uncertain"}) is None


# ── P0-W4 round 2 (F2): the REAL browser path must be able to reach "unknown" ──
#
# XHSPublisher swallows browser exceptions into an error dict, so the raising
# path above is not what production hits after a post-click timeout. The
# round-2 contract is `result_known: bool` + `error_type="publish_result_unknown"`
# on that dict — run_publish must map it to status="unknown" and leave the
# idempotency record ARMED (a definite pre-submit rejection still releases it).


def _browser_post_click_timeout() -> dict:
    """The shape XHSPublisher returns when the page dies AFTER the click."""
    return {
        "post_id": "",
        "post_url": "",
        "status": "unknown",
        "error": "Timeout 30000ms exceeded waiting for selector",
        "result_known": False,
        "error_type": "publish_result_unknown",
    }


def _browser_pre_submit_failure() -> dict:
    """The shape for a definite rejection before the submit action."""
    return {
        "post_id": "",
        "post_url": "",
        "status": "error",
        "error": "没有有效的图片文件",
        "result_known": True,
    }


def _client_returning(payload: dict):
    client = MagicMock()
    client.publish_post = AsyncMock(return_value=payload)
    client.close = AsyncMock()
    return client


async def _read_record(store, state):
    from backend.agents.publisher import PUBLISH_IDEMPOTENCY_NS, compute_publish_id

    item = await store.aget(PUBLISH_IDEMPOTENCY_NS, compute_publish_id(state))
    return getattr(item, "value", None) if item is not None else None


@pytest.mark.asyncio
async def test_browser_timeout_after_click_marks_unknown_and_keeps_guard(
    _browser_settings, monkeypatch
):
    state = _state(publish_options={"dry_run": False, "account_id": "acc_bc"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, _client_returning(_browser_post_click_timeout()))
    _mock_history(monkeypatch)
    store = _real_store()

    result = await run_publish(state, store=store)
    pr = result["publish_result"]

    assert pr["status"] == "unknown"
    assert pr["error_type"] == "publish_result_unknown"
    assert pr["result_known"] is False
    assert isinstance(pr["recovery"], dict)  # spec: recovery is never a string
    # The guard stays armed for an unknown outcome.
    assert (await _read_record(store, state))["status"] == "unknown"

    # ...so a naive second attempt is blocked instead of double-posting.
    client2 = _mock_client("p_should_not_fire")
    _patch_client(monkeypatch, client2)
    second = await run_publish(state, store=store)
    assert second["publish_result"]["error_type"] == "duplicate_publish_blocked"
    client2.publish_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_definite_failure_releases_guard(_browser_settings, monkeypatch):
    """A pre-submit rejection is known-failed: retry of the same content is
    allowed (no duplicate note was ever possible)."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_bf"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, _client_returning(_browser_pre_submit_failure()))
    _mock_history(monkeypatch)
    store = _real_store()

    result = await run_publish(state, store=store)
    pr = result["publish_result"]

    assert pr["status"] != "unknown"
    assert pr["status"] != "published"
    assert (await _read_record(store, state))["status"] == "failed"

    client2 = _mock_client("p_retry_ok")
    _patch_client(monkeypatch, client2)
    second = await run_publish(state, store=store)
    assert second["publish_result"].get("post_id") == "p_retry_ok"
    client2.publish_post.assert_awaited_once()


def test_side_effecting_submit_has_no_generic_auto_retry():
    """P0-W3/F2: a framework/tenacity auto-retry around the real submit can
    DOUBLE-POST on a timeout. Only pre-submit/read phases may auto-retry."""
    from backend.services.xhs_client import XHSClient

    assert getattr(XHSClient.publish_post, "retry", None) is None
    assert not hasattr(XHSClient.publish_post, "retry_with")


# ── P0-W4 round 2 (F3): force_publish is one-shot ─────────────────────────────


@pytest.mark.asyncio
async def test_force_publish_is_consumed_and_guard_rearmed(_browser_settings, monkeypatch):
    """After a forced publish runs, force must NOT stick to the thread: the next
    (different) publish on the same thread has to face the guard again."""
    from backend.agents.publisher import PUBLISH_IDEMPOTENCY_NS, compute_publish_id

    store = _real_store()
    state_a = _state(
        copy_content={"selected_title": "A", "body_text": "a", "hashtags": []},
        publish_options={"dry_run": False, "account_id": "acc_1", "force_publish": True},
    )
    pid_a = compute_publish_id(state_a)
    await store.aput(PUBLISH_IDEMPOTENCY_NS, pid_a, {"status": "unknown", "publish_id": pid_a})

    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _patch_client(monkeypatch, _mock_client("p_forced"))
    _mock_history(monkeypatch)

    first = await run_publish(state_a, store=store)
    assert first["publish_result"]["post_id"] == "p_forced"
    # The force flag was consumed by this execution.
    cleared_options = first["publish_options"]
    assert not cleared_options.get("force_publish")
    assert cleared_options.get("dry_run") is False  # other options survive

    # Second, DIFFERENT content published with the state-carried options must be
    # guarded again (i.e. force did not silently leak into it).
    state_b = _state(
        copy_content={"selected_title": "B", "body_text": "b", "hashtags": []},
        publish_options=cleared_options,
    )
    pid_b = compute_publish_id(state_b)
    await store.aput(PUBLISH_IDEMPOTENCY_NS, pid_b, {"status": "unknown", "publish_id": pid_b})
    client_b = _mock_client("p_must_not_fire")
    _patch_client(monkeypatch, client_b)

    second = await run_publish(state_b, store=store)
    assert second["publish_result"]["error_type"] == "duplicate_publish_blocked"
    client_b.publish_post.assert_not_awaited()
