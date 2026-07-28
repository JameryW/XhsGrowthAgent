"""End-to-end pipeline: fetch/normalize → persist → analyze → suggest.

Remote fetch failures never corrupt already-stored rows (persist only runs
after a successful fetch/normalize of the payload).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.store.base import BaseStore

from backend.db import creator_stats as stats_db
from backend.services.creator_stats.analyze import run_analysis
from backend.services.creator_stats.client import (
    CreatorStatsClient,
    CreatorStatsFetchError,
    FixtureTransport,
)
from backend.services.creator_stats.normalize import normalize_bundle, normalize_note
from backend.services.creator_stats.suggestions import suggestions_from_analysis
from backend.services.creator_stats.types import (
    ERROR_AUTH_EXPIRED,
    ERROR_BROWSER_UNAVAILABLE,
    CreatorStatsBundle,
    NoteStats,
    SyncResult,
    classify_sync_error,
)

logger = logging.getLogger("xhs_growth.creator_stats.pipeline")

# A single process may have both a manual request and the periodic worker.  A
# run-level lock makes the all-account operation an idempotent atomic unit from
# the caller's perspective and prevents two browser crawls from competing for
# the same profile.  Each account is still persisted transactionally by
# ``upsert_bundle``; a failed account never rolls back another account.
_active_accounts_sync_lock = asyncio.Lock()
_ACTIVE_ACCOUNTS_SYNC_LOCK_KEY = "xhs_growth.creator_stats.active_accounts"

# One auto-import per account after QR confirm (cleared when a new QR starts).
_post_login_sync_once: set[str] = set()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError, OverflowError):
        return default


async def _load_note_sync_state(account_id: str) -> dict[str, NoteStats] | None:
    """Persisted per-note state for incremental sync; None when unreadable."""
    try:
        rows = await stats_db.list_all_note_stats(account_id)
    except Exception:
        logger.warning("note sync state lookup failed for %s", account_id, exc_info=True)
        return None
    return {row.note_id: row for row in rows}


async def _account_freshness_skip(
    account_id: str,
) -> tuple[bool, int]:
    """Return (should_skip, retry_after_seconds) when account data is still fresh.

    Avoids opening Creator Center when we already imported recently — each
    browser session is a risk event even for light list-only crawls.
    """
    hours = _env_float("CREATOR_STATS_MIN_REFRESH_HOURS", 18.0)
    if hours <= 0:
        return False, 0
    try:
        account = await stats_db.get_account_stats(account_id)
    except Exception:
        return False, 0
    if account is None:
        return False, 0
    raw = str(getattr(account, "synced_at", "") or "").strip()
    if not raw:
        return False, 0
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except ValueError:
        return False, 0
    age = datetime.now(UTC) - ts.astimezone(UTC)
    remaining = timedelta(hours=hours) - age
    if remaining.total_seconds() <= 0:
        return False, 0
    return True, int(remaining.total_seconds())


def _fresh_snapshot_result(account_id: str, retry_after_seconds: int) -> SyncResult:
    """Build the successful no-op result used when the stored snapshot is fresh."""
    return SyncResult(
        account_id=account_id,
        source="creator_statistics",
        # Treated as success so scheduler does not backoff; no browser opened.
        account_synced=True,
        notes_imported=0,
        niche_resolution={
            "skipped": "fresh",
            "retry_after_seconds": retry_after_seconds,
            "message": (
                f"账号数据仍在刷新窗口内（{retry_after_seconds}s 后可再同步），"
                "跳过本次创作者中心访问以降低风控。"
            ),
        },
    )


def _build_incremental_filters(
    existing: dict[str, NoteStats] | None,
    *,
    recent_days: int = 7,
    body_lookback_days: int = 30,
) -> tuple[Callable[[dict[str, Any]], bool], Callable[[dict[str, Any]], bool]]:
    """Return incremental Creator Center detail and legacy body filters.

    Anti-risk-control strategy: only visit a note's detail page when it is new,
    recently published, or its list metrics moved.  Public-note body browsing
    was permanently removed; the second callable remains a compatibility
    no-op for older transports and callers.  ``existing=None`` (state
    unreadable) disables detail enrichment entirely — the list payload is
    still imported, which is the safest crawl. Timestamps are ISO strings
    compared lexicographically.
    """
    now = datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=max(0, recent_days))).isoformat()
    # Keep the keyword in the signature for older callers/configuration. It no
    # longer influences any browser action because public note pages are out of
    # scope permanently.
    _ = body_lookback_days

    def _normalize(note: dict[str, Any]) -> NoteStats | None:
        try:
            return normalize_note(note, "")
        except Exception:
            return None

    def detail_filter(note: dict[str, Any]) -> bool:
        if existing is None:
            return False
        current = _normalize(note)
        if current is None:
            return False
        previous = existing.get(current.note_id)
        if previous is None:
            return True
        published = current.published_at or previous.published_at
        if published and published >= recent_cutoff:
            return True
        return (current.views, current.likes, current.comments, current.collects) != (
            previous.views,
            previous.likes,
            previous.comments,
            previous.collects,
        )

    def body_filter(_note: dict[str, Any]) -> bool:
        """Legacy compatibility hook; public note body browsing is disabled."""
        return False

    return detail_filter, body_filter


_AUTH_PREFLIGHT_MESSAGES: dict[str, str] = {
    "stale_id_token": (
        "创作者中心登录已失效（仅残留 id_token）。请在设置页对该账号重新扫码登录后再同步。"
    ),
    "www_only": (
        "主站 cookie 存在，但创作者中心未登录（缺少 access-token-creator）。"
        "请在设置页重新扫码登录以刷新创作者中心会话后再同步。"
    ),
    "missing_creator_token": (
        "主站登录态存在，但创作者中心未登录（缺少 access-token-creator）。"
        "请在设置页重新扫码登录以刷新创作者中心会话后再同步。"
    ),
    "missing_strong_cookie": ("未检测到创作者中心登录态。请先启动绑定浏览器并扫码登录后再同步。"),
    "cdp_unavailable": "未检测到该账号可用的浏览器会话。",
    "cdp_port_down": "绑定浏览器未运行。请先启动账号 Chrome 并登录创作者中心。",
    "cdp_unreachable": "无法连接绑定浏览器的 CDP 端口。请检查 Chrome 是否已启动。",
    "logged_out": "创作者中心未登录。请先扫码登录绑定浏览器后再同步。",
}


def clear_post_login_sync_gate(account_id: str) -> None:
    """Allow the next QR-confirm on this account to auto-import stats again."""
    _post_login_sync_once.discard((account_id or "").strip())


async def preflight_creator_login(account_id: str, cdp_endpoint: str) -> SyncResult | None:
    """Skip the CDP crawl when the profile is clearly not logged in.

    Returns a failed ``SyncResult`` when login status is known-bad, or ``None``
    when the real fetch should proceed (logged in / probe inconclusive).
    """
    account_id = (account_id or "").strip()
    cdp_endpoint = (cdp_endpoint or "").strip()
    if not account_id or not cdp_endpoint:
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error="未检测到该账号可用的浏览器会话。",
            error_code=ERROR_BROWSER_UNAVAILABLE,
        )
    try:
        from backend.services.xhs_login import inspect_profile_login_status

        status = await inspect_profile_login_status(account_id, cdp_endpoint)
    except Exception as exc:
        # Probe failures must not block a real crawl — the page capture path
        # still produces the authoritative auth error.
        logger.debug("creator login preflight skipped for %s: %s", account_id, exc)
        return None

    # unavailable / unknown probes are inconclusive — still try the live page.
    if status.get("status") in ("unavailable", "unknown"):
        logger.info(
            "creator login preflight inconclusive for %s (status=%s reason=%s); crawling",
            account_id,
            status.get("status"),
            status.get("reason"),
        )
        return None

    if status.get("is_logged_in"):
        # logged_in is creator-token or verified Creator Center page evidence;
        # the www pair alone remains www_only.
        return None

    reason = str(status.get("reason") or "logged_out")
    message = _AUTH_PREFLIGHT_MESSAGES.get(reason) or _AUTH_PREFLIGHT_MESSAGES["logged_out"]
    logger.info(
        "creator login preflight blocked crawl for %s: reason=%s signals=%s",
        account_id,
        reason,
        status.get("signals"),
    )
    return SyncResult(
        account_id=account_id,
        source="creator_statistics",
        error=message,
        error_code=ERROR_AUTH_EXPIRED,
    )


async def sync_after_login(account_id: str, *, store: BaseStore | None = None) -> SyncResult | None:
    """Best-effort Creator Center import once after a successful QR login.

    Idempotent per process for a given account until ``clear_post_login_sync_gate``.
    Failures are logged and returned; they never raise into the login poll path.
    """
    account_id = (account_id or "").strip()
    if not account_id:
        return None
    if account_id in _post_login_sync_once:
        return None
    _post_login_sync_once.add(account_id)
    try:
        from backend.db.accounts import get_account_cdp_endpoint

        cdp_endpoint = (await get_account_cdp_endpoint(account_id)).strip()
        if not cdp_endpoint:
            logger.info("post-login sync skipped for %s: no cdp endpoint", account_id)
            return SyncResult(
                account_id=account_id,
                source="creator_statistics",
                error="登录成功，但未检测到浏览器会话，跳过自动同步。",
                error_code=ERROR_BROWSER_UNAVAILABLE,
            )
        result = await sync_account_stats(
            account_id,
            cookie="",
            dry_run=False,
            store=store,
            period="30d",
            run_creative_analysis=True,
            cdp_endpoint=cdp_endpoint,
            # Post-login automation is overview/list-only by default; Creator
            # Center detail enrichment remains an explicit configuration choice.
            force_light=True,
            # Preflight just confirmed login; skip a second cookie probe.
            skip_login_preflight=True,
            # A successful QR login is an explicit refresh request; do not
            # suppress the first import because the previous snapshot is fresh.
            skip_freshness_check=True,
        )
        if result.error:
            logger.info(
                "post-login sync finished with error for %s: %s",
                account_id,
                result.error,
            )
        else:
            logger.info(
                "post-login sync ok for %s: imported=%s updated=%s deleted=%s",
                account_id,
                result.notes_imported,
                result.notes_updated,
                result.notes_deleted,
            )
        return result
    except Exception as exc:
        logger.exception("post-login sync failed for %s", account_id)
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=str(exc),
            error_code=classify_sync_error(str(exc)),
        )


@asynccontextmanager
async def _distributed_active_accounts_sync_lock() -> AsyncIterator[None]:
    """Hold a PostgreSQL advisory transaction lock for the batch crawl.

    The process-local asyncio lock remains useful for SQLite/dev mode, but it
    cannot coordinate Uvicorn workers.  A transaction-scoped advisory lock
    makes the manual endpoint and every scheduler process share one critical
    section without introducing a new table or leaving a session-level lock
    behind after cancellation.
    """
    from backend.db.pool import get_pool, is_pool_ready

    if not is_pool_ready():
        yield
        return

    pool = get_pool()
    async with pool.connection() as conn, conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (_ACTIVE_ACCOUNTS_SYNC_LOCK_KEY,),
            )
            row = await cur.fetchone()
        if not row or not bool(row[0]):
            raise _ActiveAccountsSyncBusyError
        yield


class _ActiveAccountsSyncBusyError(Exception):
    """Internal sentinel used when another process owns the batch lock."""


# Bundled fixture used by dry-run / CLI --fixture path
DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "creator_stats_sample.json"
)


def _resolve_fixture_path(path: str | Path | None) -> Path:
    """Resolve fixture path; try project root when relative path misses cwd."""
    if path is None:
        return DEFAULT_FIXTURE_PATH
    p = Path(path)
    if p.is_file():
        return p
    if not p.is_absolute():
        # Project root = parents[3] of this file (…/backend/services/creator_stats/)
        alt = Path(__file__).resolve().parents[3] / p
        if alt.is_file():
            return alt
        # Also try relative to backend package parent
        alt2 = Path(__file__).resolve().parents[2].parent / p
        if alt2.is_file():
            return alt2
    return p


def load_fixture_payload(path: str | Path | None = None) -> dict[str, Any]:
    import json

    p = _resolve_fixture_path(path)
    if not p.is_file():
        raise FileNotFoundError(f"creator stats fixture not found: {p}")
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"creator stats fixture must be a JSON object: {p}")
    return data


async def persist_bundle(bundle: CreatorStatsBundle) -> tuple[int, int, int]:
    """Atomically persist an account overview and reconcile its note snapshot.

    Returns ``(notes_imported, notes_updated, notes_deleted)``.
    """
    return await stats_db.upsert_bundle(bundle.account, bundle.notes)


async def _sync_imported_account_name(bundle: CreatorStatsBundle) -> None:
    """Mirror a verified public Creator Center nickname onto the account row.

    Creator statistics keep the complete allowlisted profile snapshot, while
    account pickers read ``accounts.name``. Keep those two user-facing labels
    aligned after a successful import without letting an absent profile erase
    a name the user already has.
    """
    if bundle.account.source != "creator_statistics":
        return
    creator_name = (bundle.account.creator_name or "").strip()
    if not creator_name:
        return

    try:
        from backend.db.accounts import get_account, update_account

        account = await get_account(bundle.account.account_id)
        if account is not None and account.name != creator_name:
            await update_account(bundle.account.account_id, name=creator_name)
    except Exception as e:
        # The durable statistics snapshot already succeeded. A best-effort
        # display-name refresh must never turn that import into a failure.
        logger.warning(
            "creator account name sync skipped for %s: %s",
            bundle.account.account_id,
            e,
        )


async def import_bundle(
    bundle: CreatorStatsBundle,
    *,
    store: BaseStore | None = None,
    run_creative_analysis: bool = True,
) -> SyncResult:
    """Persist a pre-normalized bundle, analyze, and build mode suggestions.

    Persist runs first and is authoritative for import counts. Analysis failures
    do not roll back stored rows — they surface on ``error`` while
    ``account_synced`` stays True.
    """
    imported, updated, deleted = await persist_bundle(bundle)
    await _sync_imported_account_name(bundle)
    analysis = None
    suggestions: dict[str, Any] = {}
    analysis_error: str | None = None
    niche_resolution: dict[str, Any] | None = None
    if run_creative_analysis:
        try:
            analysis = await run_analysis(bundle.notes, bundle.account.account_id, store=store)
            suggestions = suggestions_from_analysis(analysis, bundle.notes)
        except Exception as e:
            logger.exception(
                "creator stats analysis failed after persist for %s",
                bundle.account.account_id,
            )
            analysis_error = f"import succeeded; analysis failed: {e}"

    # Best-effort niche bind from imported note titles/tags (never clobbers
    # account niche_source=manual — see resolve_account_niche).
    if bundle.notes:
        try:
            from backend.services.niche_resolver import resolve_account_niche

            niche_res = await resolve_account_niche(
                bundle.account.account_id,
                manual_niche="",
                notes=[n.to_dict() for n in bundle.notes],
                cold_start_default="",
                persist=True,
            )
            niche_resolution = niche_res.to_dict()
        except Exception as e:
            logger.debug("post-import niche resolve skipped: %s", e)

    return SyncResult(
        account_id=bundle.account.account_id,
        notes_imported=imported,
        notes_updated=updated,
        notes_deleted=deleted,
        account_synced=True,
        analysis=analysis,
        suggestions=suggestions,
        source=bundle.account.source,
        error=analysis_error,
        niche_resolution=niche_resolution,
    )


async def sync_from_payload(
    account_id: str,
    account_raw: dict[str, Any] | None,
    notes_raw: Any,
    *,
    profile_raw: dict[str, Any] | None = None,
    store: BaseStore | None = None,
    period: str = "30d",
    source: str = "fixture",
    run_creative_analysis: bool = True,
) -> SyncResult:
    """Normalize raw payloads → persist → analyze. Used by fixture path and tests."""
    from backend.services.creator_stats.client import normalize_period

    period_norm = normalize_period(period)
    bundle = normalize_bundle(
        account_raw,
        notes_raw,
        account_id,
        period=period_norm,
        profile_raw=profile_raw,
    )
    bundle.account.source = source
    for n in bundle.notes:
        n.source = source
    result = await import_bundle(bundle, store=store, run_creative_analysis=run_creative_analysis)
    result.source = source
    return result


async def sync_from_fixture(
    account_id: str,
    *,
    fixture_path: str | Path | None = None,
    store: BaseStore | None = None,
    run_creative_analysis: bool = True,
    period: str | None = None,
) -> SyncResult:
    """Ship entry for dry-run: load fixture JSON and run the full pipeline.

    ``period`` from the caller (CLI/API) overrides the fixture file's period so
    dry-run still exercises the requested window label on stored overview rows.
    """
    from backend.services.creator_stats.client import normalize_period

    try:
        payload = load_fixture_payload(fixture_path)
    except (OSError, ValueError) as e:
        # FileNotFoundError ⊂ OSError; JSONDecodeError ⊂ ValueError
        logger.warning("fixture load failed for %s: %s", account_id, e)
        return SyncResult(
            account_id=account_id,
            source="fixture",
            error=f"fixture load failed: {e}",
        )
    account_raw = payload.get("account") or payload.get("account_overview") or {}
    profile_raw = payload.get("profile") or payload.get("account_profile") or {}
    notes_raw = payload.get("notes") or payload.get("note_list") or payload.get("note_infos") or []
    # Caller period wins; else fixture JSON; else 30d
    period_use = normalize_period(period if period is not None else payload.get("period"))
    # Allow fixture to override account_id field but still bind to requested account
    return await sync_from_payload(
        account_id,
        account_raw,
        notes_raw,
        profile_raw=profile_raw if isinstance(profile_raw, dict) else None,
        store=store,
        period=period_use,
        source="fixture",
        run_creative_analysis=run_creative_analysis,
    )


async def sync_from_creator_center(
    account_id: str,
    cookie: str,
    *,
    store: BaseStore | None = None,
    period: str = "30d",
    client: CreatorStatsClient | None = None,
    run_creative_analysis: bool = True,
    cdp_endpoint: str = "",
    skip_login_preflight: bool = False,
    force_light: bool = False,
    skip_freshness_check: bool = False,
) -> SyncResult:
    """Live pull from creator statistics surface; on failure leave DB untouched.

    cdp_endpoint 非空 → 走 CDP 连宿主已登录 Chrome（cookie jar 自带，不用 cookie）。
    否则 fallback cookie（httpx）。注入的 client 优先级最高。

    ``force_light`` skips per-note Creator Center detail pages (default for
    scheduled syncs). Public-note body pages are never visited.
    """
    cdp_endpoint = (cdp_endpoint or "").strip()
    # An injected client is an explicit caller-owned fetch (tests, retries, or
    # a custom transport), so do not silently turn it into a freshness no-op.
    # The refresh window applies only when this function would open a live
    # Creator Center transport itself.
    if client is None and not skip_freshness_check:
        fresh, retry_s = await _account_freshness_skip(account_id)
        if fresh:
            logger.info(f"creator stats skip {account_id}: data still fresh (retry in {retry_s}s)")
            return _fresh_snapshot_result(account_id, retry_s)

    if client is None and cdp_endpoint and not skip_login_preflight:
        blocked = await preflight_creator_login(account_id, cdp_endpoint)
        if blocked is not None:
            return blocked

    fetch_kwargs: dict[str, Any] = {}
    if force_light:
        fetch_kwargs["force_light"] = True
    if client is None:
        if cdp_endpoint:
            client = CreatorStatsClient(cdp_endpoint=cdp_endpoint)
            # Incremental sync: skip per-note page visits for notes whose
            # stored state is already fresh, so a daily run only re-visits
            # new/changed notes instead of the whole history.
            existing = await _load_note_sync_state(account_id)
            fetch_kwargs["detail_filter"], fetch_kwargs["body_filter"] = _build_incremental_filters(
                existing,
                recent_days=_env_int("CREATOR_STATS_ENRICH_RECENT_DAYS", 3),
                body_lookback_days=_env_int("CREATOR_STATS_BODY_LOOKBACK_DAYS", 14),
            )
        else:
            client = CreatorStatsClient(cookie=cookie)
    try:
        bundle = await client.fetch_all(account_id, period=period, **fetch_kwargs)
    except CreatorStatsFetchError as e:
        logger.warning("creator stats fetch failed for %s: %s", account_id, e)
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=str(e),
            error_code=classify_sync_error(str(e), status_code=getattr(e, "status_code", None)),
        )
    except Exception as e:
        logger.exception("unexpected creator stats fetch error for %s", account_id)
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=str(e),
            error_code=classify_sync_error(str(e)),
        )
    finally:
        # CDP transport 连接需显式释放；httpx/fixture 的 aclose 是 no-op。
        await client.aclose()

    # Only persist after successful fetch/normalize
    result = await import_bundle(bundle, store=store, run_creative_analysis=run_creative_analysis)
    result.source = "creator_statistics"
    return result


async def sync_account_stats(
    account_id: str,
    *,
    cookie: str = "",
    dry_run: bool = False,
    fixture_path: str | Path | None = None,
    store: BaseStore | None = None,
    period: str = "30d",
    client: CreatorStatsClient | None = None,
    run_creative_analysis: bool = True,
    cdp_endpoint: str = "",
    skip_login_preflight: bool = False,
    force_light: bool = False,
    skip_freshness_check: bool = False,
) -> SyncResult:
    """Primary product entry: dry_run/fixture or live creator-center sync.

    Routing (in order):
    1. explicit ``fixture_path`` → fixture file
    2. ``dry_run=True`` → default fixture (safe CI path)
    3. injected ``client`` → use that client (tests / custom transport)
    4. non-empty ``cdp_endpoint`` → CDP 连宿主已登录 Chrome（cookie jar 自带）
    5. non-empty ``cookie`` → live creator-center pull (httpx fallback)
    6. otherwise → error (never silently write fixture rows under a real account_id)
    """
    account_id = (account_id or "").strip()
    cookie = (cookie or "").strip()
    cdp_endpoint = (cdp_endpoint or "").strip()
    if not account_id:
        return SyncResult(
            account_id="",
            source="fixture" if dry_run or fixture_path else "creator_statistics",
            error="account_id is required",
        )
    if fixture_path is not None:
        return await sync_from_fixture(
            account_id,
            fixture_path=fixture_path,
            store=store,
            run_creative_analysis=run_creative_analysis,
            period=period,
        )
    if dry_run:
        return await sync_from_fixture(
            account_id,
            store=store,
            run_creative_analysis=run_creative_analysis,
            period=period,
        )
    if client is not None:
        try:
            fetch_kw: dict[str, Any] = {"period": period}
            if force_light:
                fetch_kw["force_light"] = True
            bundle = await client.fetch_all(account_id, **fetch_kw)
        except CreatorStatsFetchError as e:
            return SyncResult(
                account_id=account_id,
                source="creator_statistics",
                error=str(e),
                error_code=classify_sync_error(str(e), status_code=getattr(e, "status_code", None)),
            )
        except Exception as e:
            logger.exception("injected client fetch failed for %s", account_id)
            return SyncResult(
                account_id=account_id,
                source="creator_statistics",
                error=str(e),
                error_code=classify_sync_error(str(e)),
            )
        finally:
            await client.aclose()
        result = await import_bundle(
            bundle, store=store, run_creative_analysis=run_creative_analysis
        )
        result.source = "creator_statistics"
        return result
    if cdp_endpoint:
        return await sync_from_creator_center(
            account_id,
            cookie="",
            store=store,
            period=period,
            client=None,
            run_creative_analysis=run_creative_analysis,
            cdp_endpoint=cdp_endpoint,
            skip_login_preflight=skip_login_preflight,
            force_light=force_light,
            skip_freshness_check=skip_freshness_check,
        )
    if not cookie:
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=(
                "cdp_endpoint or cookie required for live creator-stats sync; "
                "pass dry_run=True to use the fixture path"
            ),
            error_code=ERROR_BROWSER_UNAVAILABLE,
        )
    return await sync_from_creator_center(
        account_id,
        cookie,
        store=store,
        period=period,
        client=None,
        run_creative_analysis=run_creative_analysis,
        skip_login_preflight=skip_login_preflight,
        force_light=force_light,
        skip_freshness_check=skip_freshness_check,
    )


# 上次成功完成全量同步的时刻（进程内）。冷却期内再次触发（主要是手动
# sync-all）直接跳过——短时间内反复全量爬创作者中心是明显的机器/滥用模式。
_last_successful_sync_finished_at: datetime | None = None
# Count consecutive list-only scheduled runs; occasionally allow a deep run.
_scheduled_light_streak: int = 0


def _resolve_force_light(*, prefer_light: bool | None) -> bool:
    """Decide whether this batch must stay list-only (no note detail pages).

    Scheduled jobs default to force_light. Manual API defaults to chance-based
    light runs inside the transport (prefer_light=False).
    ``CREATOR_STATS_DEEP_EVERY_N_RUNS`` lets scheduled jobs deep-enrich rarely
    when explicitly set to a positive integer; an unset value stays list-only.
    """
    global _scheduled_light_streak
    if prefer_light is False:
        return False
    if prefer_light is True:
        deep_every = _env_int("CREATOR_STATS_DEEP_EVERY_N_RUNS", 0)
        if deep_every <= 0:
            return True
        _scheduled_light_streak += 1
        if _scheduled_light_streak >= deep_every:
            _scheduled_light_streak = 0
            # Still only 40% chance to deep-enrich when due — keep rare.
            return random.random() >= 0.4
        return True
    # prefer_light is None → env default for scheduled-style safety
    if _env_int("CREATOR_STATS_SCHEDULED_FORCE_LIGHT", 1) == 1:
        return _resolve_force_light(prefer_light=True)
    return False


def _has_successful_live_sync(result: dict[str, Any]) -> bool:
    """Return whether a batch performed at least one real successful import.

    Freshness skips deliberately use ``account_synced=True`` so callers treat
    them as a successful no-op.  They must not, however, start the global
    post-sync cooldown because no browser session or remote fetch occurred.
    """
    for item in result.get("results") or []:
        if not isinstance(item, dict) or not item.get("account_synced"):
            continue
        resolution = item.get("niche_resolution")
        if isinstance(resolution, dict) and resolution.get("skipped"):
            continue
        return True
    return False


async def sync_all_active_accounts(
    *,
    store: BaseStore | None = None,
    period: str = "30d",
    run_creative_analysis: bool = True,
    prefer_light: bool | None = None,
    skip_freshness_check: bool = False,
) -> dict[str, Any]:
    """Run the active-account batch under local and distributed locks.

    冷却：距上次成功同步不足 ``CREATOR_STATS_SYNC_COOLDOWN_MINUTES``（默认
    45，0 关闭）时返回 ``status="cooldown"`` 而不爬取。调度器把 cooldown
    视为非失败（不触发退避）。

    ``prefer_light``: True = list-only (scheduled default), False = allow deep
    enrich (manual), None = follow ``CREATOR_STATS_SCHEDULED_FORCE_LIGHT``.
    ``skip_freshness_check``: explicit manual/login-triggered syncs can bypass
    the per-account refresh window; scheduled jobs should leave it ``False``.
    """
    global _last_successful_sync_finished_at
    if _active_accounts_sync_lock.locked():
        return {
            "ok": False,
            "status": "already_running",
            "active_accounts": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }
    from backend.services.xhs_risk_gate import (
        clear_sync_auth_failure,
        note_sync_auth_failure,
    )

    cooldown_minutes = _env_int("CREATOR_STATS_SYNC_COOLDOWN_MINUTES", 45)
    if cooldown_minutes > 0 and _last_successful_sync_finished_at is not None:
        elapsed = datetime.now(UTC) - _last_successful_sync_finished_at
        remaining = timedelta(minutes=cooldown_minutes) - elapsed
        if remaining.total_seconds() > 0:
            logger.info(
                "active accounts sync skipped: cooldown %.0fs remaining",
                remaining.total_seconds(),
            )
            return {
                "ok": False,
                "status": "cooldown",
                "active_accounts": 0,
                "succeeded": 0,
                "failed": 0,
                "results": [],
                "error": (
                    f"距离上次成功同步不足 {cooldown_minutes} 分钟，"
                    "为避免频繁访问创作者中心已跳过本次同步。"
                ),
                "retry_after_seconds": int(remaining.total_seconds()),
            }

    try:
        async with _distributed_active_accounts_sync_lock():
            result = await _sync_all_active_accounts_locked(
                store=store,
                period=period,
                run_creative_analysis=run_creative_analysis,
                # Resolve the scheduled mode after the active account and its
                # auth gate have been checked, so skipped cycles do not consume
                # one of the light-run slots.
                force_light=None,
                prefer_light=prefer_light,
                skip_freshness_check=skip_freshness_check,
            )
    except _ActiveAccountsSyncBusyError:
        return {
            "ok": False,
            "status": "already_running",
            "active_accounts": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }
    # Empty, fresh, and other skipped batches are successful no-ops, not
    # browser syncs; only a real successful import starts the cooldown.
    if _has_successful_live_sync(result):
        _last_successful_sync_finished_at = datetime.now(UTC)
    # Per-account gates: clear on success, block on auth/shell failures.
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("account_id") or "")
        if not aid:
            continue
        if item.get("account_synced"):
            clear_sync_auth_failure(aid)
            continue
        err = str(item.get("error") or "")
        code = str(item.get("error_code") or "")
        text = f"{code} {err}".lower()
        if (
            code == ERROR_AUTH_EXPIRED
            or "401" in text
            or "auth" in text
            or "re-login" in text
            or "登录" in err
        ):
            note_sync_auth_failure(aid, reason=code or "AUTH_EXPIRED")
    return result


async def _sync_all_active_accounts_locked(
    *,
    store: BaseStore | None = None,
    period: str = "30d",
    run_creative_analysis: bool = True,
    force_light: bool | None = False,
    prefer_light: bool | None = None,
    skip_freshness_check: bool = False,
) -> dict[str, Any]:
    """Import Creator Center data for the currently active account only.

    Only the single account returned by ``get_active_account()`` is synced, so
    switching the active account immediately stops the previous account's data
    from being refreshed.  The operation shares a process-wide lock with the
    scheduler and the HTTP trigger, so a second invocation returns
    ``already_running`` instead of starting a duplicate browser crawl.
    """
    global _scheduled_light_streak
    if _active_accounts_sync_lock.locked():
        return {
            "ok": False,
            "status": "already_running",
            "active_accounts": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }

    async with _active_accounts_sync_lock:
        started_at = datetime.now(UTC).isoformat()
        from backend.db.accounts import get_account_cdp_endpoint, get_active_account
        from backend.services.xhs_risk_gate import check_sync_auth_cooldown

        try:
            current = await get_active_account()
        except Exception as exc:
            logger.exception("active account lookup failed before creator stats sync")
            return {
                "ok": False,
                "status": "failed",
                "active_accounts": 0,
                "succeeded": 0,
                "failed": 1,
                "results": [],
                "error": str(exc),
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        accounts = [current] if current is not None else []

        if current is not None:
            auth_block = check_sync_auth_cooldown(str(current.id))
            if auth_block is not None:
                logger.info(
                    f"active account sync skipped: auth-fail cooldown "
                    f"{auth_block.retry_after_seconds}s"
                )
                return {
                    "ok": False,
                    "status": "cooldown",
                    "active_accounts": 1,
                    "succeeded": 0,
                    "failed": 0,
                    "results": [],
                    "error": auth_block.message,
                    "retry_after_seconds": auth_block.retry_after_seconds,
                    "risk_code": auth_block.risk_code,
                }

        results: list[dict[str, Any]] = []
        for account in accounts:
            account_id = str(account.id).strip()
            if not account_id:
                continue
            try:
                cdp_endpoint = (await get_account_cdp_endpoint(account_id)).strip()
            except Exception as exc:
                logger.warning(
                    "CDP endpoint lookup failed for active account %s: %s", account_id, exc
                )
                cdp_endpoint = ""

            if not cdp_endpoint:
                result = SyncResult(
                    account_id=account_id,
                    source="creator_statistics",
                    error="未检测到该激活账号可用的浏览器会话。",
                    error_code=ERROR_BROWSER_UNAVAILABLE,
                )
            else:
                streak_before: int | None = None
                try:
                    # Do not consume a scheduled light-run slot when the
                    # persisted snapshot is fresh enough to skip the browser.
                    if force_light is None and not skip_freshness_check:
                        fresh, retry_s = await _account_freshness_skip(account_id)
                        if fresh:
                            result = _fresh_snapshot_result(account_id, retry_s)
                            results.append(result.to_dict())
                            continue
                    if force_light is None:
                        streak_before = _scheduled_light_streak
                        force_light = _resolve_force_light(prefer_light=prefer_light)
                    result = await sync_account_stats(
                        account_id,
                        cookie="",
                        dry_run=False,
                        store=store,
                        period=period,
                        run_creative_analysis=run_creative_analysis,
                        cdp_endpoint=cdp_endpoint,
                        force_light=force_light,
                        skip_freshness_check=skip_freshness_check,
                    )
                    if streak_before is not None and (result.error or not result.account_synced):
                        # A failed attempt is not a completed scheduled run;
                        # leave the deep-run cadence unchanged for the retry.
                        _scheduled_light_streak = streak_before
                except Exception as exc:
                    if streak_before is not None:
                        _scheduled_light_streak = streak_before
                    # A single account must not abort the remaining active
                    # accounts in this batch.
                    logger.exception(f"creator stats sync failed for active account {account_id}")
                    result = SyncResult(
                        account_id=account_id,
                        source="creator_statistics",
                        error=str(exc),
                        error_code=classify_sync_error(str(exc)),
                    )
            results.append(result.to_dict())

        succeeded = sum(1 for item in results if item.get("account_synced"))
        failed = len(results) - succeeded
        return {
            "ok": failed == 0,
            "status": "completed",
            "active_accounts": len(accounts),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "force_light": bool(force_light),
        }


def fixture_transport_from_file(path: str | Path | None = None) -> FixtureTransport:
    payload = load_fixture_payload(path)
    return FixtureTransport(
        account_payload=payload.get("account") or {},
        notes_payload=payload.get("notes") or [],
    )
