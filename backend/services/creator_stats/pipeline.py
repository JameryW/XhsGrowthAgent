"""End-to-end pipeline: fetch/normalize → persist → analyze → suggest.

Remote fetch failures never corrupt already-stored rows (persist only runs
after a successful fetch/normalize of the payload).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
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
from backend.services.creator_stats.normalize import normalize_bundle
from backend.services.creator_stats.suggestions import suggestions_from_analysis
from backend.services.creator_stats.types import (
    CreatorStatsBundle,
    SyncResult,
)

logger = logging.getLogger("xhs_growth.creator_stats.pipeline")

# A single process may have both a manual request and the periodic worker.  A
# run-level lock makes the all-account operation an idempotent atomic unit from
# the caller's perspective and prevents two browser crawls from competing for
# the same profile.  Each account is still persisted transactionally by
# ``upsert_bundle``; a failed account never rolls back another account.
_active_accounts_sync_lock = asyncio.Lock()

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


async def persist_bundle(bundle: CreatorStatsBundle) -> tuple[int, int]:
    """Atomically persist an account overview and its imported notes."""
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
    imported, updated = await persist_bundle(bundle)
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
) -> SyncResult:
    """Live pull from creator statistics surface; on failure leave DB untouched.

    cdp_endpoint 非空 → 走 CDP 连宿主已登录 Chrome（cookie jar 自带，不用 cookie）。
    否则 fallback cookie（httpx）。注入的 client 优先级最高。
    """
    if client is None:
        if cdp_endpoint:
            client = CreatorStatsClient(cdp_endpoint=cdp_endpoint)
        else:
            client = CreatorStatsClient(cookie=cookie)
    try:
        bundle = await client.fetch_all(account_id, period=period)
    except CreatorStatsFetchError as e:
        logger.warning("creator stats fetch failed for %s: %s", account_id, e)
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=str(e),
        )
    except Exception as e:
        logger.exception("unexpected creator stats fetch error for %s", account_id)
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=str(e),
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
            bundle = await client.fetch_all(account_id, period=period)
        except CreatorStatsFetchError as e:
            return SyncResult(account_id=account_id, source="creator_statistics", error=str(e))
        except Exception as e:
            logger.exception("injected client fetch failed for %s", account_id)
            return SyncResult(account_id=account_id, source="creator_statistics", error=str(e))
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
        )
    if not cookie:
        return SyncResult(
            account_id=account_id,
            source="creator_statistics",
            error=(
                "cdp_endpoint or cookie required for live creator-stats sync; "
                "pass dry_run=True to use the fixture path"
            ),
        )
    return await sync_from_creator_center(
        account_id,
        cookie,
        store=store,
        period=period,
        client=None,
        run_creative_analysis=run_creative_analysis,
    )


async def sync_all_active_accounts(
    *,
    store: BaseStore | None = None,
    period: str = "30d",
    run_creative_analysis: bool = True,
) -> dict[str, Any]:
    """Import Creator Center data for every active account, sequentially.

    Only rows with ``accounts.is_active = TRUE`` are selected.  The operation
    shares a process-wide lock with the scheduler and the HTTP trigger, so a
    second invocation returns ``already_running`` instead of starting a
    duplicate browser crawl.  Network failures are isolated per account and
    represented in the returned batch summary.
    """
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
        from backend.db.accounts import get_account_cdp_endpoint, list_active_accounts

        try:
            accounts = await list_active_accounts()
        except Exception as exc:
            logger.exception("list active accounts failed before creator stats sync")
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
                )
            else:
                try:
                    result = await sync_account_stats(
                        account_id,
                        cookie="",
                        dry_run=False,
                        store=store,
                        period=period,
                        run_creative_analysis=run_creative_analysis,
                        cdp_endpoint=cdp_endpoint,
                    )
                except Exception as exc:
                    # A single account must not abort the remaining active
                    # accounts in this batch.
                    logger.exception("creator stats sync failed for active account %s", account_id)
                    result = SyncResult(
                        account_id=account_id,
                        source="creator_statistics",
                        error=str(exc),
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
        }


def fixture_transport_from_file(path: str | Path | None = None) -> FixtureTransport:
    payload = load_fixture_payload(path)
    return FixtureTransport(
        account_payload=payload.get("account") or {},
        notes_payload=payload.get("notes") or [],
    )
