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
        "niche": "母婴",
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
    client.publish_note = AsyncMock(
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
    """Stub only the browser layer; the tool, the Gateway and the catalog all run.

    Patching the publisher *factory* (rather than the Gateway or the tool) is
    what makes these tests exercise the real capability path: ``xhs.publish``
    still normalises its own payload and still reports its verdict through
    ``DomainOutcome``, so a contract change breaks here instead of in prod.
    """
    seen: dict[str, str] = {}
    calls: list[str] = []

    def _factory(cdp_endpoint: str = ""):
        seen["cdp_endpoint"] = cdp_endpoint
        calls.append(cdp_endpoint)
        return client

    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", _factory)
    client.cdp_seen = seen
    client.factory_calls = calls
    return client


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
    """account_id in publish_options → per-account CDP endpoint reaches the tool."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9225")
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    kwargs = m_client.cdp_seen
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9225"
    assert result["publish_result"]["post_id"] == "p1"


@pytest.mark.asyncio
async def test_falls_back_to_global_when_no_account(_browser_settings, mock_store, monkeypatch):
    """No account selected → the deployment's *declared* endpoint is the grant.

    A blank account id means "this deployment", so the browser it may use is the
    one ``XHS_CDP_ENDPOINT`` declares — not one discovered by probing, which is
    what P2a-S5b ruled out for the grant (reachability is not entitlement).
    """
    state = _state(publish_options={"dry_run": False})
    client = _mock_client("p2")
    _browser_settings.platform.cdp_endpoint = "http://global:9223"
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    kwargs = m_client.cdp_seen
    assert kwargs["cdp_endpoint"] == "http://global:9223"


@pytest.mark.asyncio
async def test_per_account_cdp_endpoint_passed_to_client(
    _browser_settings, mock_store, monkeypatch
):
    """Selected account with a cdp_port → per-account endpoint reaches the tool,
    overriding the global _resolve_cdp_endpoint result."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    kwargs = m_client.cdp_seen
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9223"


@pytest.mark.asyncio
async def test_selected_account_without_a_binding_is_refused_not_borrowed(
    _browser_settings, mock_store, monkeypatch
):
    """A *selected* account with no port binding must not borrow the global browser.

    Before P2a-S5c this published: the per-account endpoint was empty, so the
    global one was used, and the note went out through whichever session that
    Chrome held — i.e. one account's selection, another account's identity.  The
    grant now says what the mechanism actually does, so this is a refusal with a
    named fix rather than a silent impersonation.

    The deployment endpoint stays declared on purpose: the refusal must come
    from the *account's* missing binding, not from there being no browser at all.
    """
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")  # account has no port binding
    _browser_settings.platform.cdp_endpoint = "http://global:9223"
    client = _mock_client("p1")
    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", lambda *a, **kw: client)

    result = await run_publish(state, store=mock_store)

    assert client.publish_note.await_count == 0
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "missing_publish_credential"
    assert pr["recovery"]["action"] == "reconfigure"


@pytest.mark.asyncio
async def test_missing_cdp_endpoint_returns_failed(_browser_settings, mock_store, monkeypatch):
    """Selected account without CDP endpoint → fail fast, no publisher built."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_empty"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")  # no per-account CDP profile
    monkeypatch.setattr(
        "backend.agents.publisher._resolve_cdp_endpoint",
        lambda _s: "",  # no global CDP either
    )
    m_client = MagicMock()
    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", lambda *a, **kw: m_client)

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

    kwargs = m_client.cdp_seen
    assert kwargs["cdp_endpoint"] == "http://127.0.0.1:9223"
    assert result["publish_result"]["post_id"] == "p_cdp"


@pytest.mark.asyncio
async def test_classifies_auth_error(_browser_settings, mock_store, monkeypatch):
    """publish throws auth error → auth_expired error_type + structured recovery."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")

    client = MagicMock()
    client.publish_note = AsyncMock(side_effect=RuntimeError("cookie expired, login required"))
    client.close = AsyncMock()
    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", lambda *a, **kw: client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "auth_expired"
    assert isinstance(pr["recovery"], dict)


@pytest.mark.asyncio
async def test_preserves_publish_service_error(_browser_settings, mock_store, monkeypatch):
    """publish_note returning a platform error keeps error/recovery in state."""

    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")

    client = MagicMock()
    client.publish_note = AsyncMock(
        return_value={"post_id": "", "status": "failed", "error": "未绑定手机号"}
    )
    client.close = AsyncMock()
    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", lambda *a, **kw: client)
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

    # Real publish ran (publish_note awaited), not the mock path
    client.publish_note.assert_awaited_once()
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
    client_fail.publish_note = AsyncMock(return_value={"post_id": "", "status": "failed"})
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
    client.publish_note = AsyncMock(
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
    # No account selected → the deployment's declared endpoint carries the grant.
    _browser_settings.platform.cdp_endpoint = "http://global:9223"
    client = _mock_client("p_sched")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    submit = client.publish_note.await_args.kwargs
    assert submit["scheduled_time"] == ""


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
    client.publish_note = AsyncMock(side_effect=TimeoutError("page load timed out"))
    client.close = AsyncMock()
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=_real_store())

    pr = result["publish_result"]
    assert pr["status"] == "unknown"
    assert isinstance(pr["recovery"], dict)  # spec: recovery must stay a dict
    # The wording of a timeout now belongs to the runtime: the Gateway is what
    # measured it and what names it ("timeout after <n>s").  The method name
    # used to appear here only because the exception text was passed through
    # verbatim.  What must NOT have changed is the verdict -- status "unknown"
    # and error_type "publish_result_unknown" -- since that is what keeps the
    # duplicate-post guard armed.
    assert "timeout" in str(pr["error"]).lower()


@pytest.mark.asyncio
async def test_non_timeout_error_still_marks_failed(_browser_settings, monkeypatch):
    """Non-timeout submit errors keep the old "failed" classification."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_f"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = MagicMock()
    client.publish_note = AsyncMock(side_effect=RuntimeError("boom"))
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
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)
    store = _real_store()

    first = await run_publish(state, store=store)
    assert first["publish_result"]["status"] == "published"

    second = await run_publish(state, store=store)

    assert second["publish_result"]["status"] == "failed"
    assert second["publish_result"]["error_type"] == "duplicate_publish_blocked"
    assert isinstance(second["publish_result"]["recovery"], dict)
    # publish_note only ran for the first attempt (one publisher built).
    client.publish_note.assert_awaited_once()
    assert len(client.factory_calls) == 1


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
    client.publish_note.assert_not_awaited()


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
    client.publish_note.assert_awaited_once()


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

    def _boom(*_args, **_kwargs):
        raise AssertionError("the dry-run path must never build a publisher")

    monkeypatch.setattr("backend.tools.xhs.publisher._get_publisher", _boom)

    state = {
        "session_id": "s",
        "account_id": "a",
        "dry_run": True,  # workflow-level dry_run
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "visual_plan": {},
        "content_plan": {},
        "publish_options": {"dry_run": False},  # user tries to flip it
    }
    # _boom above is the assertion: building a publisher at all would raise.
    result = await PublisherAgent().execute(state, store=AsyncMock())

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
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS, pid, {"status": "published", "publish_id": pid, "post_id": "pp"}
    )

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "published"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.CONFIRMED
    assert ledger.extra.get("reconcile_evidence", {}).get("source") == "idempotency_record"


@pytest.mark.asyncio
async def test_reconcile_unknown_publish_finds_history_match():
    """A matching published entry in content history reconciles the unknown.

    Seeds an UNKNOWN ledger row (the typical post-submit-no-verdict case) and
    asserts local ContentHistory evidence advances UNKNOWN → CONFIRMED.
    """
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.memory.store import MemoryManager
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r2"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )
    mm = MemoryManager("acc_r2")
    await store.aput(
        mm.content_history_ns,
        "note-1",
        {"title": "t", "status": "published", "post_id": "note-1"},
    )

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "published"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.CONFIRMED
    assert ledger.extra.get("reconcile_evidence", {}).get("source") == "content_history"
    assert ledger.extra.get("post_id") == "note-1"


@pytest.mark.asyncio
async def test_reconcile_unknown_publish_uncertain_without_evidence():
    """Uncertain reconcile must not mutate an UNKNOWN ledger row."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r3"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "uncertain"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN
    assert "reconcile_evidence" not in ledger.extra


@pytest.mark.asyncio
async def test_reconcile_ledger_confirm_failure_does_not_block_return(monkeypatch):
    """Ledger write failure is best-effort: reconcile still returns published."""
    from backend.agents import publisher as publisher_mod
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(publish_options={"dry_run": False, "account_id": "acc_r4"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "published", "publish_id": pid, "post_id": "pp4"},
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("store down")

    monkeypatch.setattr(publisher_mod.EffectLedger, "mark", _boom)

    recon = await reconcile_unknown_publish(state, store)
    assert recon["status"] == "published"
    assert recon["evidence"]["source"] == "idempotency_record"
    # mark blew up: seeded row stays CONFIRMED without reconcile_evidence.
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.CONFIRMED
    assert "reconcile_evidence" not in ledger.extra


# ── 票 5ak: platform note-list reconcile after local miss ─────────────────────


@pytest.mark.asyncio
async def test_default_platform_fetcher_skips_without_cookie(monkeypatch):
    """Default fetcher: no cookie → empty list (no CreatorStatsClient call)."""
    from backend.agents.publisher import _default_fetch_platform_notes
    from backend.services.xhs_credentials import XhsCredential

    async def _no_cookie(account_id: str, **_kw):
        return XhsCredential(account_id=account_id, cookie="")

    monkeypatch.setattr(
        "backend.services.xhs_credentials.load_credential",
        _no_cookie,
    )

    def _boom(*_a, **_k):
        raise AssertionError("CreatorStatsClient must not run without cookie")

    monkeypatch.setattr(
        "backend.services.creator_stats.client.CreatorStatsClient",
        _boom,
    )
    assert await _default_fetch_platform_notes("acc_nocookie") == []


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_hit_confirms_ledger():
    """Exact title on creator note list → published + EffectLedger CONFIRMED."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "平台命中标题", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )
    calls: list[str] = []

    async def _fetcher(account_id: str):
        calls.append(account_id)
        return [
            {"display_title": " 平台命中标题 ", "noteId": "note-plat-1"},
            {"title": "其他", "id": "other"},
        ]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_fetcher)
    assert recon["status"] == "published"
    assert recon["evidence"]["source"] == "platform_note_list"
    assert recon["evidence"]["post_id"] == "note-plat-1"
    assert calls == ["acc_plat"]
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.CONFIRMED
    assert ledger.extra.get("reconcile_evidence", {}).get("source") == "platform_note_list"
    assert ledger.extra.get("post_id") == "note-plat-1"


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_empty_stays_uncertain():
    """Empty platform list → uncertain; UNKNOWN ledger untouched."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "无命中", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat_empty"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    async def _empty(_account_id: str):
        return []

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_empty)
    assert recon["status"] == "uncertain"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN
    assert "reconcile_evidence" not in ledger.extra


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_title_miss_stays_uncertain():
    """Non-empty list without exact title match → uncertain (no fake-confirm)."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "目标标题", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat_miss"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    async def _miss(_account_id: str):
        return [
            {"title": "目标标题相近", "id": "n-near"},
            {"title": "完全不同", "note_id": "n-other"},
        ]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_miss)
    assert recon["status"] == "uncertain"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_title_without_id_stays_uncertain():
    """Exact title but missing note id → uncertain (evidence requires post_id)."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "有标题无 id", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat_noid"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    async def _no_id(_account_id: str):
        return [{"display_title": "有标题无 id"}]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_no_id)
    assert recon["status"] == "uncertain"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_fetcher_error_stays_uncertain():
    """Fetcher raise → warn path → uncertain; never fake-confirm."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "拉列表失败", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat_err"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    async def _boom(_account_id: str):
        raise RuntimeError("creator stats HTTP 503")

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_boom)
    assert recon["status"] == "uncertain"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_local_confirm_skips_platform_fetcher():
    """Idempotency / ContentHistory hit must not call platform_note_fetcher."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )

    state = _state(publish_options={"dry_run": False, "account_id": "acc_skip_plat"})
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "published", "publish_id": pid, "post_id": "local-pp"},
    )
    calls: list[str] = []

    async def _fetcher(account_id: str):
        calls.append(account_id)
        return [{"title": "t", "id": "should-not-matter"}]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_fetcher)
    assert recon["status"] == "published"
    assert recon["evidence"]["source"] == "idempotency_record"
    assert calls == []


@pytest.mark.asyncio
async def test_reconcile_no_title_skips_platform_fetcher():
    """Empty selected_title must not invoke platform_note_fetcher."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "   ", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_no_title"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )
    calls: list[str] = []

    async def _fetcher(account_id: str):
        calls.append(account_id)
        return [{"title": "anything", "id": "n1"}]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_fetcher)
    assert recon["status"] == "uncertain"
    assert calls == []
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_content_history_hit_skips_platform_fetcher():
    """ContentHistory local confirm must not call the platform fetcher."""
    from backend.agents.publisher import (
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.memory.store import MemoryManager

    state = _state(
        copy_content={"selected_title": "历史命中", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_hist_skip"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )
    mm = MemoryManager("acc_hist_skip")
    await store.aput(
        mm.content_history_ns,
        "hist-1",
        {"title": "历史命中", "status": "published", "post_id": "hist-1"},
    )
    calls: list[str] = []

    async def _fetcher(account_id: str):
        calls.append(account_id)
        raise AssertionError("platform must not run after local confirm")

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_fetcher)
    assert recon["status"] == "published"
    assert recon["evidence"]["source"] == "content_history"
    assert calls == []


# ── 票 5al: default platform fetcher multi-page (max 3) ───────────────────────


@pytest.mark.asyncio
async def test_default_platform_fetcher_fetches_up_to_three_pages(monkeypatch):
    """Full pages keep going until ``_PLATFORM_NOTE_LIST_MAX_PAGES`` (票 5al)."""
    from backend.agents.publisher import (
        _PLATFORM_NOTE_LIST_MAX_PAGES,
        _PLATFORM_NOTE_LIST_PAGE_SIZE,
        _default_fetch_platform_notes,
    )
    from backend.services.xhs_credentials import XhsCredential

    async def _cookie(account_id: str, **_kw):
        return XhsCredential(account_id=account_id, cookie="k=v")

    monkeypatch.setattr(
        "backend.services.xhs_credentials.load_credential",
        _cookie,
    )

    calls: list[tuple[int, int]] = []

    class _FakeClient:
        def __init__(self, **_kw):
            pass

        async def fetch_note_list(self, *, page_num: int = 1, page_size: int = 50, **_kw):
            calls.append((page_num, page_size))
            return {
                "notes": [
                    {"title": f"t{page_num}-{i}", "id": f"n{page_num}-{i}"}
                    for i in range(page_size)
                ]
            }

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "backend.services.creator_stats.client.CreatorStatsClient",
        _FakeClient,
    )

    notes = await _default_fetch_platform_notes("acc_pages")
    assert _PLATFORM_NOTE_LIST_MAX_PAGES == 3
    assert calls == [
        (1, _PLATFORM_NOTE_LIST_PAGE_SIZE),
        (2, _PLATFORM_NOTE_LIST_PAGE_SIZE),
        (3, _PLATFORM_NOTE_LIST_PAGE_SIZE),
    ]
    assert len(notes) == _PLATFORM_NOTE_LIST_MAX_PAGES * _PLATFORM_NOTE_LIST_PAGE_SIZE


@pytest.mark.asyncio
async def test_default_platform_fetcher_stops_on_short_page(monkeypatch):
    """len(items) < page_size stops early — no further page requests."""
    from backend.agents.publisher import (
        _PLATFORM_NOTE_LIST_PAGE_SIZE,
        _default_fetch_platform_notes,
    )
    from backend.services.xhs_credentials import XhsCredential

    async def _cookie(account_id: str, **_kw):
        return XhsCredential(account_id=account_id, cookie="k=v")

    monkeypatch.setattr(
        "backend.services.xhs_credentials.load_credential",
        _cookie,
    )

    calls: list[int] = []

    class _FakeClient:
        def __init__(self, **_kw):
            pass

        async def fetch_note_list(self, *, page_num: int = 1, page_size: int = 50, **_kw):
            calls.append(page_num)
            if page_num == 1:
                return {
                    "notes": [
                        {"title": f"p1-{i}", "id": f"a{i}"}
                        for i in range(_PLATFORM_NOTE_LIST_PAGE_SIZE)
                    ]
                }
            return {"notes": [{"title": "short-tail", "id": "tail-1"}]}

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "backend.services.creator_stats.client.CreatorStatsClient",
        _FakeClient,
    )

    notes = await _default_fetch_platform_notes("acc_short")
    assert calls == [1, 2]
    assert len(notes) == _PLATFORM_NOTE_LIST_PAGE_SIZE + 1
    assert notes[-1]["id"] == "tail-1"


@pytest.mark.asyncio
async def test_default_platform_fetcher_stops_on_empty_page(monkeypatch):
    """Empty extract_note_items page stops early (no page 3)."""
    from backend.agents.publisher import (
        _PLATFORM_NOTE_LIST_PAGE_SIZE,
        _default_fetch_platform_notes,
    )
    from backend.services.xhs_credentials import XhsCredential

    async def _cookie(account_id: str, **_kw):
        return XhsCredential(account_id=account_id, cookie="k=v")

    monkeypatch.setattr(
        "backend.services.xhs_credentials.load_credential",
        _cookie,
    )

    calls: list[int] = []

    class _FakeClient:
        def __init__(self, **_kw):
            pass

        async def fetch_note_list(self, *, page_num: int = 1, page_size: int = 50, **_kw):
            calls.append(page_num)
            if page_num == 1:
                return {
                    "notes": [
                        {"title": f"only-{i}", "id": f"o{i}"}
                        for i in range(_PLATFORM_NOTE_LIST_PAGE_SIZE)
                    ]
                }
            return {"notes": []}

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "backend.services.creator_stats.client.CreatorStatsClient",
        _FakeClient,
    )

    notes = await _default_fetch_platform_notes("acc_empty_p2")
    assert calls == [1, 2]
    assert len(notes) == _PLATFORM_NOTE_LIST_PAGE_SIZE


@pytest.mark.asyncio
async def test_default_platform_fetcher_page_error_propagates(monkeypatch):
    """Any page raise propagates (reconcile outer catch → uncertain)."""
    from backend.agents.publisher import _default_fetch_platform_notes
    from backend.services.xhs_credentials import XhsCredential

    async def _cookie(account_id: str, **_kw):
        return XhsCredential(account_id=account_id, cookie="k=v")

    monkeypatch.setattr(
        "backend.services.xhs_credentials.load_credential",
        _cookie,
    )

    class _FakeClient:
        def __init__(self, **_kw):
            pass

        async def fetch_note_list(self, *, page_num: int = 1, page_size: int = 50, **_kw):
            if page_num == 1:
                return {"notes": [{"title": "ok", "id": "n1"} for _ in range(50)]}
            raise RuntimeError("creator stats HTTP 503 on page 2")

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "backend.services.creator_stats.client.CreatorStatsClient",
        _FakeClient,
    )

    with pytest.raises(RuntimeError, match="page 2"):
        await _default_fetch_platform_notes("acc_page_err")


@pytest.mark.asyncio
async def test_reconcile_platform_note_list_page2_hit_confirms_ledger():
    """Title only after a full page of fillers still confirms (票 5al)."""
    from backend.agents.publisher import (
        _PLATFORM_NOTE_LIST_PAGE_SIZE,
        PUBLISH_IDEMPOTENCY_NS,
        compute_publish_id,
        reconcile_unknown_publish,
    )
    from backend.state.effects import EffectLedger, EffectStatus

    state = _state(
        copy_content={"selected_title": "第二页命中", "body_text": "b"},
        publish_options={"dry_run": False, "account_id": "acc_plat_p2"},
    )
    store = _real_store()
    pid = compute_publish_id(state)
    await store.aput(
        PUBLISH_IDEMPOTENCY_NS,
        pid,
        {"status": "unknown", "publish_id": pid},
    )

    async def _fetcher(_account_id: str):
        fillers = [
            {"title": f"filler-{i}", "id": f"f{i}"} for i in range(_PLATFORM_NOTE_LIST_PAGE_SIZE)
        ]
        return fillers + [{"title": "第二页命中", "note_id": "note-p2"}]

    recon = await reconcile_unknown_publish(state, store, platform_note_fetcher=_fetcher)
    assert recon["status"] == "published"
    assert recon["evidence"]["source"] == "platform_note_list"
    assert recon["evidence"]["post_id"] == "note-p2"
    ledger = await EffectLedger(store, PUBLISH_IDEMPOTENCY_NS).get(pid)
    assert ledger is not None
    assert ledger.status is EffectStatus.CONFIRMED
    assert ledger.extra.get("reconcile_evidence", {}).get("source") == "platform_note_list"
    assert ledger.extra.get("post_id") == "note-p2"


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
    client.publish_note = AsyncMock(return_value=payload)
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
    client2.publish_note.assert_not_awaited()


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
    client2.publish_note.assert_awaited_once()


def test_side_effecting_submit_has_no_generic_auto_retry():
    """P0-W3/F2: a framework/tenacity auto-retry around the real submit can
    DOUBLE-POST on a timeout. Only pre-submit/read phases may auto-retry.

    The submit is the ``xhs.publish`` tool now (P2a-S4a), so the guard is
    checked on the tool *and* on the catalogue: a tenacity decoration on the
    function is the shape this test always looked for, and ``max_attempts``
    is the runtime's own answer to the same question. See
    ``backend/tools/runtime/catalog.py`` for why the key alone is not
    enough to turn retry on.
    """
    from backend.tools.runtime.catalog import build_registry
    from backend.tools.xhs.publisher import xhs_publisher

    assert getattr(xhs_publisher, "retry", None) is None
    assert not hasattr(xhs_publisher, "retry_with")
    assert build_registry().spec("xhs.publish").retry_policy.max_attempts == 1


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
    client_b.publish_note.assert_not_awaited()


# ── P2a-S4a: the mainline submit goes through the Tool Gateway ───────────────


def test_publisher_declares_its_capability():
    """The P1c-S5 gate reads ``tool_capabilities`` with ``ast.Assign``.

    An annotated class attribute is an ``ast.AnnAssign`` and is invisible to
    it, which fails the gate with UNDECLARED -- hence the deliberate absence
    of a type annotation on the declaration.
    """
    from backend.agents.publisher import PublisherAgent
    from backend.tools.runtime.catalog import build_registry

    assert PublisherAgent.tool_capabilities == ("xhs.publish",)
    assert build_registry().spec("xhs.publish").capability == "xhs.publish"


@pytest.mark.asyncio
async def test_real_publish_reaches_the_gateway_with_the_whole_payload(
    _browser_settings, monkeypatch
):
    """One Gateway invocation of "xhs.publish", carrying account + CDP + key.

    This is the assertion the orphan capability could not make before: the
    mainline used to build its own ``XHSClient``, so nothing checked that the
    account id ever reached the platform layer (P2a-S2's defect).
    """
    from backend.agents.publisher import compute_publish_id
    from backend.tools.runtime.gateway import ToolGateway

    state = _state(publish_options={"dry_run": False, "account_id": "acc_gw"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9226")
    _patch_client(monkeypatch, _mock_client("p_gw"))
    _mock_history(monkeypatch)

    captured: list[tuple[str, dict, str]] = []
    real_invoke = ToolGateway.invoke

    async def _spy(self, capability, payload=None, *, thread_id="", granted_scopes=None):
        captured.append((capability, dict(payload or {}), thread_id))
        return await real_invoke(
            self, capability, payload, thread_id=thread_id, granted_scopes=granted_scopes
        )

    monkeypatch.setattr(ToolGateway, "invoke", _spy)

    result = await run_publish(state, store=_real_store())

    assert result["publish_result"]["status"] == "published"
    assert [capability for capability, _, _ in captured] == ["xhs.publish"]
    _, payload, thread_id = captured[0]
    assert payload["account_id"] == "acc_gw"
    assert payload["cdp_endpoint"] == "http://127.0.0.1:9226"
    assert payload["idempotency_key"] == compute_publish_id(state)
    assert payload["title"] == "t"
    # The thread id is how a lost answer ("unknown") is traced back to the run
    # that submitted it, so it has to travel with the invocation.
    assert thread_id == "test_session"


@pytest.mark.asyncio
async def test_unattributed_publish_sends_an_empty_account_id(_browser_settings, monkeypatch):
    """No account anywhere -> the platform layer gets "", never "default".

    P2a-S2 pinned a per-account publish cooldown that had no production
    writer.  Wiring the mainline in (S4a) must not "fix" that by inventing an
    account: handing "default" to the platform layer files every unattributed
    post under "account:default", which silently changes the meaning of a
    guardrail that works today.  The idempotency *record* keeps "default" --
    it only needs a stable string to hash, and re-keying it would orphan
    every existing record.
    """
    state = _state(account_id="", publish_options={"dry_run": False})
    # ``state["account_id"]`` is only a label; the grant follows the *selected*
    # account, so an unattributed publish is entitled by the deployment's own
    # declaration — which is also the endpoint it will publish through.
    _browser_settings.platform.cdp_endpoint = "http://global:9228"
    client = _mock_client("p_anon")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=_real_store())

    assert client.publish_note.await_args.kwargs["account_id"] == ""


@pytest.mark.asyncio
async def test_platform_verdict_survives_the_gateway_round_trip(_browser_settings, monkeypatch):
    """A platform rejection is a DOMAIN outcome, not a runtime failure.

    It must come back with its own ``status``/``error``/``error_type`` so the
    idempotency guard can be *released* -- the opposite of a timeout, which
    must leave it armed.
    """
    state = _state(publish_options={"dry_run": False, "account_id": "acc_v"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9227")
    client = MagicMock()
    client.publish_note = AsyncMock(
        return_value={"status": "failed", "error": "cookie expired, login required"}
    )
    client.close = AsyncMock()
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=_real_store())

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "auth_expired"
    assert pr["recovery"]["action"] == "reconfigure"


# ── P2a-S5c: the declared auth_scope is applied on this path too ─────────────


class _RecordingTools:
    """A stand-in for ``agent.tools`` that records the grant it was handed."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple[str, ...] | None]] = []

    async def invoke(
        self,
        capability: str,
        payload: object,
        *,
        thread_id: str = "",
        granted_scopes: tuple[str, ...] | None = None,
    ):
        from backend.tools.runtime.models import ToolResult

        self.seen.append((capability, granted_scopes))
        return ToolResult(
            capability=capability,
            ok=True,
            value={"post_id": "p_grant", "status": "published"},
        )


@pytest.mark.asyncio
async def test_the_resolved_grant_travels_with_the_invocation(
    _browser_settings, mock_store, monkeypatch
):
    """``xhs.publish`` declares ``auth_scope`` — this path now applies it.

    The assertion is on what the Gateway *received*, not on a helper's return
    value: a resolved tuple that never reaches ``invoke`` would leave the
    requirement exactly as decorative as it was before.
    """
    from types import SimpleNamespace

    state = _state(publish_options={"dry_run": False, "account_id": "acc_g"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    _mock_history(monkeypatch)
    tools = _RecordingTools()

    await run_publish(state, store=mock_store, agent=SimpleNamespace(tools=tools))

    # No cookie in this environment: the grant is the browser, so it is write
    # only.  A read scope here would claim an HTTP identity that does not exist.
    assert tools.seen == [("xhs.publish", ("xhs:write",))]


@pytest.mark.asyncio
async def test_the_refusal_leaves_no_durable_trace(_browser_settings, monkeypatch):
    """An unauthorized publish must not write the PREPARED record.

    The record exists so a crash *between deciding and submitting* stays
    distinguishable.  Nothing was decided here — writing it would make the retry
    path reconcile an intent that was never authorized.
    """
    from unittest.mock import patch

    state = _state(publish_options={"dry_run": False, "account_id": "acc_none"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")
    # A browser exists at the deployment level, so the account's missing
    # binding — not a missing endpoint — is what the refusal is about.
    _browser_settings.platform.cdp_endpoint = "http://global:9223"
    monkeypatch.setenv("XHS_COOKIE", "web_session=no-login-material")

    with patch("backend.agents.publisher._write_publish_record", new=AsyncMock()) as recorded:
        result = await run_publish(state, store=_real_store())

    assert recorded.await_count == 0
    assert result["publish_result"]["error_type"] == "missing_publish_credential"


# ── 票 5k: a publish blocked before it was attempted is a countable fact ──────
#
# Three/four preconditions return a `publish_result` without ever invoking the
# capability: inactive account, no CDP endpoint, no write grant, duplicate
# attempt. The per-thread result already says *what* happened; the action entry
# is what lets an operator ask "*how often*, and why" across threads (the same
# gap P2a-S5b closed for human refusals at the publish gate).


async def _publish_blocked_events(state):
    """The ``kind:"action"`` entries this publish path wrote for a block."""
    from backend.db.workflow_events import list_events
    from backend.state.events import (
        ACTION_EVENT_KIND,
        ACTION_PUBLISH_BLOCKED,
        resolve_thread_id,
    )

    events = await list_events(resolve_thread_id(state), kind=ACTION_EVENT_KIND)
    return [event for event in events if event.get("action") == ACTION_PUBLISH_BLOCKED]


@pytest.mark.asyncio
async def test_an_inactive_account_block_is_recorded(_browser_settings, monkeypatch):
    state = _state(publish_options={"dry_run": False, "account_id": "acc_off"})
    _mock_account_active(monkeypatch, is_active=False)

    result = await run_publish(state, store=_real_store())

    assert result["publish_result"]["error_type"] == "account_inactive"
    events = await _publish_blocked_events(state)
    assert len(events) == 1
    assert (events[0].get("action"), events[0].get("reason"), events[0].get("account_id")) == (
        "publish_blocked",
        "account_inactive",
        "acc_off",
    )


@pytest.mark.asyncio
async def test_a_missing_cdp_endpoint_block_is_recorded(_browser_settings, monkeypatch):
    state = _state(publish_options={"dry_run": False, "account_id": "acc_nocdp"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")
    _browser_settings.platform.cdp_endpoint = ""

    result = await run_publish(state, store=_real_store())

    assert result["publish_result"]["error_type"] == "missing_cdp_endpoint"
    events = await _publish_blocked_events(state)
    assert len(events) == 1
    assert events[0].get("reason") == "missing_cdp_endpoint"
    assert events[0].get("account_id") == "acc_nocdp"


@pytest.mark.asyncio
async def test_a_missing_write_grant_block_is_recorded(_browser_settings, monkeypatch):
    """The publish-retry path (`agent=None`) must record it too — it has no
    tool-trace context, so the action entry is the only durable observation."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_none"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="")
    # A browser exists at the deployment level; what is missing is the grant.
    _browser_settings.platform.cdp_endpoint = "http://global:9223"
    monkeypatch.setenv("XHS_COOKIE", "web_session=no-login-material")

    result = await run_publish(state, store=_real_store())

    assert result["publish_result"]["error_type"] == "missing_publish_credential"
    events = await _publish_blocked_events(state)
    assert len(events) == 1
    assert events[0].get("reason") == "missing_credential"
    assert events[0].get("account_id") == "acc_none"


@pytest.mark.asyncio
async def test_a_duplicate_publish_block_is_recorded_with_its_prior(_browser_settings, monkeypatch):
    from backend.agents.publisher import compute_publish_id

    state = _state(publish_options={"dry_run": False, "account_id": "acc_dup"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_once")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)
    store = _real_store()

    first = await run_publish(state, store=store)
    assert first["publish_result"]["status"] == "published"

    second = await run_publish(state, store=store)

    assert second["publish_result"]["error_type"] == "duplicate_publish_blocked"
    events = await _publish_blocked_events(state)
    assert len(events) == 1
    event = events[0]
    assert event.get("reason") == "duplicate_publish"
    assert event.get("publish_id") == compute_publish_id(state)
    assert event.get("prior_status") == "confirmed", (
        "the machine-readable why: the prior effect already succeeded"
    )
    assert event.get("account_id") == "acc_dup"


@pytest.mark.asyncio
async def test_a_successful_publish_records_no_blocked_event(_browser_settings, monkeypatch):
    """The positive control: the event means "blocked", so a publish that ran
    must not carry one. Without this, emitting on every publish would pass the
    four tests above."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_ok"})
    _mock_account_active(monkeypatch)
    _mock_cdp_endpoint(monkeypatch, endpoint="http://127.0.0.1:9223")
    client = _mock_client("p_ok")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=_real_store())

    assert result["publish_result"]["status"] == "published"
    assert await _publish_blocked_events(state) == []
