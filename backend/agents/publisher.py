"""Publisher agent — handles posting workflow and A/B testing."""

from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    # BaseStore / XHSGrowthState / Settings only appears in annotations;
    # importing langgraph.store.base + state.schema + pydantic_settings at
    # module load pulls langchain_core.runnables + langgraph.graph.message +
    # pydantic.v1 on every app import (publisher is eagerly loaded by the
    # free route singleton). Deferred to TYPE_CHECKING; runtime Settings()
    # calls use a function-local import.
    from langgraph.store.base import BaseStore

    from backend.config.settings import Settings
    from backend.state.schema import XHSGrowthState

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.services.text_cover import generate_text_cover_image
from backend.state.enums import WorkflowPhase

logger = logging.getLogger("xhs_growth.agents.publisher")


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


# ── P0-W4: deterministic publish idempotency key ─────────────────────────────

# Idempotency records live in the graph store under this namespace; key =
# publish_id. Recorded BEFORE the real (non-dry-run) submit action with
# status "unknown" (result genuinely unknown until confirmed), then upgraded
# to "published" or downgraded to "failed". A record in ("published",
# "unknown") blocks any further real publish of the same key (same account +
# content + images inside the time window) unless the caller passes an
# explicit force (publish-retry force=true → publish_options.force_publish).
PUBLISH_IDEMPOTENCY_NS: tuple[str, ...] = ("publish", "idempotency")
# Time window folded into the key: after it rolls over, the same content may
# legitimately be re-published as a NEW attempt.
_PUBLISH_ID_WINDOW_SECONDS = 6 * 3600

_PUBLISH_BLOCKED_ERROR_TYPE = "duplicate_publish_blocked"
# P0-W4 (F2): the submit action was initiated and the platform gave us no
# verdict (post-click timeout, dead page, "发布状态未知"). Reporting that as
# "failed" would release the idempotency guard and invite a duplicate note, so
# it flows through the pipeline as status="unknown" + this typed error.
_PUBLISH_RESULT_UNKNOWN = "publish_result_unknown"

# Structured recovery dict (spec: never a bare string) for an unknown outcome.
_UNKNOWN_OUTCOME_RECOVERY: dict[str, Any] = {
    "message": "发布提交后结果不明，发帖可能已成功",
    "action": "wait",
    "action_label": "去人工核对",
    "hint": "请先在小红书近期笔记中确认是否已发布；确认可安全重发时，"
    "在 /publish-retry 请求体中显式传 force=true。",
}


def _submit_outcome_is_unknown(result: dict[str, Any], status: str) -> bool:
    """True when the browser layer finished WITHOUT a verdict on our submit.

    Honest contract from XHSPublisher (P0-W4 F2): ``result_known=False`` or the
    typed ``publish_result_unknown`` error, and the legacy no-verdict
    ``"unknown"``/``"pending"`` statuses, all mean "the note may exist".
    Anything else (a platform rejection message, an auth failure before the
    click) is a definite outcome the guard may be released for.
    """
    if result.get("result_known") is False:
        return True
    if str(result.get("error_type") or "") == _PUBLISH_RESULT_UNKNOWN:
        return True
    return status in ("unknown", "pending")


def _publish_account_id(state: Mapping[str, Any]) -> str:
    publish_options = state.get("publish_options") or {}
    return (
        str(publish_options.get("account_id") or state.get("account_id") or "default").strip()
        or "default"
    )


def compute_publish_id(state: Mapping[str, Any]) -> str:
    """Deterministic idempotency key: hash(account + content + images + window).

    Same workflow content published to the same account inside the same time
    window yields the same publish_id, so accidental double-fires (node
    re-execution, naive publish-retry) can be detected before the real submit.
    """
    import hashlib
    import time

    copy = state.get("copy_content") or {}
    visual = state.get("visual_plan") or {}
    images = _as_str_list(visual.get("image_paths")) or _as_str_list(visual.get("generated_images"))
    payload = {
        "account_id": _publish_account_id(state),
        "title": str(copy.get("selected_title") or ""),
        "body": str(copy.get("body_text") or ""),
        "hashtags": _as_str_list(copy.get("hashtags")),
        "cta": str(copy.get("cta") or ""),
        "images": sorted(images),
        "window": int(time.time() // _PUBLISH_ID_WINDOW_SECONDS),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _is_timeout_error(exc: BaseException) -> bool:
    """Browser/HTTP timeout detection across playwright/httpx/asyncio shapes.

    asyncio's TimeoutError is the builtin; playwright's and some httpx
    timeouts are distinct classes — match by name as a fallback.
    """
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower()


async def _read_publish_record(store: BaseStore | None, publish_id: str) -> dict[str, Any] | None:
    """Best-effort read of a prior idempotency record (dict value only)."""
    if store is None or not publish_id:
        return None
    try:
        existing = await store.aget(PUBLISH_IDEMPOTENCY_NS, publish_id)
    except Exception as e:  # storage outage must not crash publish
        logger.warning("publish idempotency read failed (proceeding): %s", e)
        return None
    value = getattr(existing, "value", None) if existing is not None else None
    return value if isinstance(value, dict) else None


async def _write_publish_record(
    store: BaseStore | None, publish_id: str, record: dict[str, Any]
) -> None:
    """Best-effort write of the idempotency record (checkpoint/event mirror)."""
    if store is None or not publish_id:
        return
    try:
        await store.aput(PUBLISH_IDEMPOTENCY_NS, publish_id, record)
    except Exception as e:
        logger.warning("publish idempotency record write failed (non-blocking): %s", e)


def _blocked_duplicate_result(publish_id: str, prior: dict[str, Any]) -> dict[str, Any]:
    prior_status = str(prior.get("status") or "unknown")
    if prior_status == "published":
        message = "相同内容在近期已成功发布（幂等键命中），已阻止重复发帖。"
    else:
        message = (
            "相同内容近期发起过真实发布且结果不明（幂等键命中），"
            "已阻止自动重复发帖；请先人工核对小红书近期笔记。"
        )
    return {
        "post_id": "",
        "post_url": "",
        "status": "failed",
        "error": message,
        "error_type": _PUBLISH_BLOCKED_ERROR_TYPE,
        "publish_id": publish_id,
        # Structured recovery dict (spec: never a bare string).
        "recovery": {
            "message": message,
            "action": "wait",
            "action_label": "稍后处理",
            "hint": (
                "如确认该笔记未发布成功，可使用发布重试并显式 force=true；"
                "如已发布成功，请勿重复发布。"
            ),
        },
    }


async def reconcile_unknown_publish(state: dict[str, Any], store: BaseStore) -> dict[str, Any]:
    """Reconcile a publish whose result is unknown BEFORE any re-publish.

    Uses the two identity mechanisms that already exist:
    1. the P0-W4 idempotency record (upgraded to "published" with the real
       post_id by the completing run), and
    2. the platform_post_id/link_status matching trail — ContentHistory rows
       keyed by post_id carrying {title, status:"published"} — searched for a
       recent note matching this workflow's title.

    Returns {"status": "published", "evidence": {...}} when a match confirms
    the post exists, else {"status": "uncertain"} — the caller must then demand
    an explicit human force decision instead of silently re-posting.
    """
    publish_id = compute_publish_id(state)
    record = await _read_publish_record(store, publish_id)
    if record and record.get("status") == "published":
        return {"status": "published", "evidence": {"source": "idempotency_record", **record}}

    copy = state.get("copy_content") or {}
    title = str(copy.get("selected_title") or "").strip()
    if title and store is not None:
        try:
            from backend.memory.store import MemoryManager

            mm = MemoryManager(_publish_account_id(state))
            items = await store.asearch(mm.content_history_ns, query=title, limit=10)
            for item in items:
                value = getattr(item, "value", None)
                if (
                    isinstance(value, dict)
                    and str(value.get("title") or "").strip() == title
                    and str(value.get("status") or "") == "published"
                ):
                    return {
                        "status": "published",
                        "evidence": {
                            "source": "content_history",
                            "post_id": str(value.get("post_id") or getattr(item, "key", "") or ""),
                        },
                    }
        except Exception as e:
            logger.warning("unknown-publish reconciliation failed: %s", e)
    return {"status": "uncertain"}


def evaluate_unknown_publish_retry(
    pr_status: Any, force: bool, reconciled: dict[str, Any]
) -> dict[str, Any] | None:
    """Pure gate for /publish-retry against a status="unknown" publish.

    Returns an early-response payload dict when the retry must NOT run, or
    None to proceed:

    - non-unknown statuses are unaffected (None).
    - unknown + force=true → proceed (None); the caller marks the attempt as
      forced (publish_options.force_publish) so the idempotency guard lets the
      explicit human decision through.
    - unknown + no force + reconciliation CONFIRMED published → do not retry;
      report "reconciled".
    - unknown + no force + uncertain → refuse with "requires_force" and tell
      the caller an explicit force=true is needed.
    """
    if str(pr_status or "") != "unknown":
        return None
    if force:
        return None
    if (reconciled or {}).get("status") == "published":
        evidence = (reconciled or {}).get("evidence") or {}
        return {
            "status": "reconciled",
            "message": (
                "对账确认：该笔记已存在于账号近期发布记录中，未重复发布。"
                f"匹配来源: {evidence.get('source', 'unknown')}"
            ),
            "evidence": evidence,
        }
    return {
        "status": "requires_force",
        "message": (
            "上次发布结果不明（可能已发帖成功），且自动对账无法确认。"
            "请先人工核对小红书近期笔记；确认可安全重发时，请在请求体中显式传 force=true。"
        ),
    }


def _with_publish_link_metadata(
    publish_result: dict[str, Any], state: XHSGrowthState | dict[str, Any]
) -> dict[str, Any]:
    """Attach the durable workflow-to-platform identity to a publish result.

    A workflow checkpoint is the first durable record available at publish
    time.  We keep the platform id separate from the display/synthetic id so
    analytics can only collapse an imported note after an explicit id match.
    ``mock_*`` ids are intentionally not treated as platform identities.
    """
    thread_id = str(state.get("session_id") or state.get("thread_id") or "").strip()
    raw_post_id = str(publish_result.get("post_id") or "").strip()
    platform_post_id = "" if raw_post_id.startswith("mock_") else raw_post_id
    result = dict(publish_result)
    result.update(
        {
            "workflow_thread_id": thread_id,
            "platform_post_id": platform_post_id,
            # The imported-note linker upgrades this to ``linked`` only after
            # Creator Center returns the same normalized platform id.
            "link_status": "unmatched",
        }
    )
    return result


def _normalize_scheduled_time(value: Any) -> str:
    """Return a future schedule time formatted for XHS, or empty for immediate publish."""

    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""

    parsed: datetime | None = None
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue

    if parsed is None:
        logger.warning("忽略无法解析的定时发布时间: %s", raw)
        return ""

    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    if parsed <= now:
        logger.info("忽略已过期的定时发布时间: %s", raw)
        return ""

    if parsed.tzinfo:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M")


def _resolve_cdp_endpoint(settings: Settings) -> str:
    """Resolve the real-Chrome CDP endpoint across old/new runtime settings."""

    platform = settings.platform
    endpoint = getattr(platform, "cdp_endpoint", "") or os.getenv("XHS_CDP_ENDPOINT", "")
    if endpoint:
        return endpoint

    host = "host.containers.internal"
    port = 9223
    try:
        address = socket.gethostbyname(host)
        with socket.create_connection((address, port), timeout=0.2):
            return f"http://{address}:{port}"
    except OSError:
        return ""


class PublisherAgent(BaseAgent):
    task_type = TaskType.PUBLISHING
    agent_name = "publisher"
    prompt_file = "publisher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        # 获取配置
        from backend.config.settings import Settings

        settings = Settings()
        use_browser = settings.platform.use_browser

        # dry_run guard — defense in depth. Two sources of truth, both must
        # agree to allow real publish:
        #   1. Top-level state["dry_run"] — set by /start when user requests
        #      dry_run. This is the workflow-level contract: a dry_run workflow
        #      must NEVER call the real XHS publish API, regardless of what
        #      publish_options says (a user could pass publish_options.dry_run
        #      =False in the approve decision and silently flip it).
        #   2. publish_options["dry_run"] — set by review.py /approve (defaults
        #      to True when the decision omits publish_options).
        # Either being True triggers the mock path.
        publish_options = state.get("publish_options") or {}
        is_dry_run = bool(state.get("dry_run")) or publish_options.get("dry_run", False)

        if is_dry_run or not use_browser:
            if is_dry_run:
                logger.info("dry_run=True，执行试运行发布")
            else:
                logger.warning("use_browser=False，跳过真实发布")
            # 返回模拟结果
            import datetime

            publish_result = _with_publish_link_metadata(
                {
                    "post_id": f"mock_{state.get('session_id', '0')}",
                    "post_url": "https://www.xiaohongshu.com/explore/mock",
                    "published_at": datetime.datetime.now().isoformat(),
                    "ab_variant": None,
                    "status": "mock_published",
                    "account_id": publish_options.get("account_id") or state.get("account_id", ""),
                },
                state,
            )
            return {
                "publish_result": publish_result,
                "phase": WorkflowPhase.PUBLISHING,
            }

        return await run_publish(state, store)


async def run_publish(state: XHSGrowthState | dict[str, Any], store: BaseStore) -> dict[str, Any]:
    """Execute the real (non-dry-run) publish against Xiaohongshu.

    Extracted from PublisherAgent.execute so failed-publish retries (the
    /api/workflow/publish-retry endpoint) can re-run just the publish step
    with the workflow's existing content, without re-running the creation
    chain or honoring dry_run. Returns the same shape as execute.

    Outcome contract (P0-W4): publish_result.status is "published" (verdict:
    posted), a definite failure status (verdict: not posted), or "unknown" —
    the submit action was initiated and the platform gave no verdict, so the
    note may exist. Only the first two rewrite the idempotency record;
    "unknown" leaves it armed until reconciliation or an explicit force.
    When this execution consumed ``publish_options.force_publish`` it also
    returns cleared ``publish_options`` (one-shot force, F3).
    """
    copy = state.get("copy_content", {})
    plan = state.get("content_plan", {})
    publish_options = state.get("publish_options") or {}
    publish_account_id = publish_options.get("account_id")
    from backend.config.settings import Settings

    settings = Settings()

    # CDP multi-profile: per-account endpoint takes priority over the global
    # _resolve_cdp_endpoint. Accounts without a port binding (cdp_port=0 or
    # account missing) fall back to the global endpoint — backward compat with
    # the single-account .chrome-profile/ flow.
    cdp_endpoint = _resolve_cdp_endpoint(settings)
    if publish_account_id:
        # 停用账号早 fail：is_active=false 直接拒绝，避免浪费一次真实 Chrome 发布
        # 等 XHS 平台返回 auth_expired。
        from backend.db.accounts import get_account

        account = await get_account(publish_account_id)
        if account is None or not account.is_active:
            logger.warning(f"账号 {publish_account_id} 未激活或不存在，跳过发布")
            # Explicit annotation: publish_result is a heterogeneous dict
            # (str fields + nested recovery dict + bools). Without it mypy
            # joins the first literal's values to Collection[str] and rejects
            # the later `result_known: bool` writes.
            publish_result: dict[str, Any] = {
                "post_id": "",
                "post_url": "",
                "status": "failed",
                "error": f"账号 {publish_account_id} 已停用，无法发布",
                "error_type": "account_inactive",
                "recovery": {
                    "message": "该账号已停用，发布前需在设置页重新激活",
                    "action": "reconfigure",
                    "action_label": "重新激活",
                    "hint": "请在设置页将该账号重新激活后再发布",
                },
            }
            return {
                "publish_result": _with_publish_link_metadata(publish_result, state),
                "phase": WorkflowPhase.PUBLISHING,
            }

        from backend.db.accounts import get_account_cdp_endpoint

        per_account_endpoint = await get_account_cdp_endpoint(publish_account_id)
        if per_account_endpoint:
            cdp_endpoint = per_account_endpoint

        if not cdp_endpoint:
            logger.error("账号 %s 未绑定可用 CDP endpoint，无法发布", publish_account_id)
            publish_result = {
                "post_id": "",
                "post_url": "",
                "status": "failed",
                "error": f"账号 {publish_account_id} 未绑定 CDP profile 登录态",
                "error_type": "missing_cdp_endpoint",
                # Structured recovery dict — same shape as
                # classify_publish_error() returns, so Dashboard.vue's
                # publishError.recovery.{hint,action,action_label} renders.
                "recovery": {
                    "message": "该账号未绑定可用 CDP profile 登录态",
                    "action": "reconfigure",
                    "action_label": "去设置",
                    "hint": "请在设置页启动该账号浏览器并完成扫码登录后再发布",
                },
            }
            return {
                "publish_result": _with_publish_link_metadata(publish_result, state),
                "phase": WorkflowPhase.PUBLISHING,
            }
        logger.info("按选中账号 %s 的 CDP profile 登录态发布", publish_account_id)

    # ── P0-W4 idempotency gate (real publish path only) ──
    # Deterministic key recorded BEFORE the real submit action. A previous
    # attempt with a known outcome ("published" or result-unknown "unknown")
    # for the same account+content+images+window blocks this publish unless
    # the caller passed an explicit force (publish-retry force=true writes
    # publish_options.force_publish — consumed ONCE, see F3 below). dry-run
    # traffic never reaches this code (guarded in PublisherAgent.execute / the
    # mock branch above).
    publish_id = compute_publish_id(state)
    force_publish = bool(publish_options.get("force_publish"))
    if not force_publish:
        prior = await _read_publish_record(store, publish_id)
        if prior and prior.get("status") in ("published", "unknown"):
            logger.warning(
                "阻止重复真实发布: publish_id=%s 已有 status=%s 的幂等记录",
                publish_id,
                prior.get("status"),
            )
            return {
                "publish_result": _with_publish_link_metadata(
                    _blocked_duplicate_result(publish_id, prior), state
                ),
                "phase": WorkflowPhase.PUBLISHING,
            }
    # Record the attempt as result-unknown BEFORE submitting, so a crash /
    # lost response in between still blocks duplicate real publishes.
    await _write_publish_record(
        store,
        publish_id,
        {
            "status": "unknown",
            "publish_id": publish_id,
            "account_id": _publish_account_id(state),
            "thread_id": str(state.get("session_id") or state.get("thread_id") or ""),
            "recorded_at": datetime.now().isoformat(),
            "forced": force_publish,
        },
    )

    # P0-W4 (F3): an explicit force is ONE-SHOT. Whatever the outcome of this
    # execution, the flag is cleared out of publish_options (returned to the
    # caller / written back to state) so the NEXT publish on this thread faces
    # the idempotency guard again instead of silently bypassing it forever.
    cleared_publish_options: dict[str, Any] | None = (
        {**publish_options, "force_publish": False} if force_publish else None
    )

    # 调用真实发布服务
    from backend.services.xhs_client import XHSClient, XHSPost

    client = XHSClient(
        cookie="",
        user_id="",
        use_browser=True,
        headless=False,
        cdp_endpoint=cdp_endpoint,
    )

    try:
        # 从 visual_plan 提取图片路径
        visual = state.get("visual_plan", {}) or {}
        image_paths = _as_str_list(visual.get("image_paths"))
        if not image_paths:
            # 尝试从 generated_images 提取
            image_paths = _as_str_list(visual.get("generated_images"))
        if not image_paths:
            title = copy.get("selected_title") or plan.get("selected_topic") or "小红书笔记"
            output_dir = Path("/tmp/xhs_generated_covers") / str(
                state.get("session_id") or "default"
            )
            cover_path = generate_text_cover_image(
                title=str(title),
                key_points=_as_str_list(plan.get("key_points")),
                color_palette=_as_str_list(visual.get("color_palette")),
                output_dir=output_dir,
            )
            image_paths = [cover_path]
            logger.info("无素材图，已生成文字封面: %s", cover_path)

        # 构造发布数据
        post = XHSPost(
            title=copy.get("selected_title", ""),
            body=copy.get("body_text", ""),
            hashtags=copy.get("hashtags", []),
            image_paths=image_paths,
            category=cast(str, plan.get("category", "")),
            location=cast(str, plan.get("location", "")),
            is_private=False,
            scheduled_time=_normalize_scheduled_time(plan.get("suggested_timing", "")),
        )

        # 执行发布（真实提交动作 — 之后的一切超时都是"结果不明"而非确定失败）
        result = await client.publish_post(post)

        raw_status = str(result.get("status") or "unknown")
        # P0-W4 (F2): the browser layer swallows its own exceptions into a result
        # dict, so the "unknown" case normally arrives HERE (not as a raised
        # exception). Honour its honest verdict-or-nothing contract.
        outcome_unknown = _submit_outcome_is_unknown(result, raw_status)
        status = "unknown" if outcome_unknown else raw_status

        publish_result = {
            "post_id": result.get("post_id", ""),
            "post_url": result.get("post_url", ""),
            "published_at": result.get("published_at", ""),
            "ab_variant": cast(Any, None),
            "status": status,
        }
        if result.get("error"):
            publish_result["error"] = result["error"]
            from backend.api.errors import classify_publish_error

            error_type, recovery = classify_publish_error(str(result["error"]))
            publish_result["error_type"] = result.get("error_type") or error_type.value
            publish_result["recovery"] = result.get("recovery") or recovery
        if outcome_unknown:
            # Re-label the typed error/recovery as "result unknown" even when
            # the browser reported a bare timeout string: the duplicate-post
            # risk, not the network diagnosis, is what the caller must act on.
            publish_result["error_type"] = _PUBLISH_RESULT_UNKNOWN
            publish_result["recovery"] = _UNKNOWN_OUTCOME_RECOVERY
            publish_result["result_known"] = False
            publish_result["note"] = (
                "提交动作已发起但结果不明——发布可能已成功，请先人工核对小红书近期笔记"
            )

        # P0-W4: idempotency key rides the result for events/checkpoint audit.
        publish_result["publish_id"] = publish_id

        # Outcome-known: upgrade or downgrade the pre-recorded "unknown". A
        # platform-reported definite failure (status != published, verdict known)
        # releases the guard; an unknown outcome leaves it ARMED on purpose.
        if status == "published":
            await _write_publish_record(
                store,
                publish_id,
                {
                    "status": "published",
                    "publish_id": publish_id,
                    "post_id": str(publish_result.get("post_id") or ""),
                    "thread_id": str(state.get("session_id") or ""),
                },
            )
        elif outcome_unknown:
            logger.error(
                "发布结果不明（提交后无判定）: publish_id=%s 幂等护栏保持 armed，"
                "需对账或显式 force 才能再次真实发布",
                publish_id,
            )
        else:
            await _write_publish_record(
                store,
                publish_id,
                {
                    "status": "failed",
                    "publish_id": publish_id,
                    "thread_id": str(state.get("session_id") or ""),
                    "error": str(publish_result.get("error") or ""),
                },
            )

        logger.info(f"发布完成: {publish_result['post_id']}")

    except Exception as e:
        logger.error(f"发布失败: {type(e).__name__}: {e}")
        from backend.api.errors import classify_publish_error

        error_type, recovery = classify_publish_error(str(e))
        # P0-W4: distinguish "failed" (definitely not posted) from "unknown"
        # (result not observable). After the real submit action was entered, a
        # browser/HTTP timeout means the note may well have been published —
        # reporting that as "failed" invites a duplicate post. The idempotency
        # record deliberately STAYS "unknown" so the next real publish is
        # blocked until reconciliation/force.
        is_unknown = _is_timeout_error(e)
        publish_result = {
            "post_id": "",
            "post_url": "",
            "status": "unknown" if is_unknown else "failed",
            "error": str(e),
            "error_type": error_type.value,
            "recovery": recovery,
        }
        if is_unknown:
            publish_result["publish_id"] = publish_id
            publish_result["result_known"] = False
            publish_result["note"] = (
                "提交后超时，发帖结果不明——发布可能已成功，请先人工核对小红书近期笔记"
            )
        else:
            await _write_publish_record(
                store,
                publish_id,
                {
                    "status": "failed",
                    "publish_id": publish_id,
                    "thread_id": str(state.get("session_id") or ""),
                    "error": str(e),
                },
            )

    finally:
        await client.close()

    # 记录到长期记忆
    account_id = state.get("account_id", "default")
    # ponytail: 真实 XHS 发布成功只 redirect 到 /publish/success，post_id 从 URL
    # regex 提取常为空（见 xhs_publisher._wait_for_success）。原 gate `post_id`
    # 非空会让真实成功跳过 ContentHistory 记录。用 status=="published" 判成功，
    # 仍把 post_id（可能为空）传下去做 key。
    pub_ok = publish_result.get("status") == "published"
    if pub_ok or publish_result.get("post_id"):
        try:
            from backend.memory.content_history import ContentHistory

            history = ContentHistory(account_id)
            # Include IDs for calibration chain and content_type for recall filtering
            visual_plan = state.get("visual_plan", {})
            await history.record(
                store,
                post_id=cast(str, publish_result["post_id"]),
                data={
                    "title": copy.get("selected_title", ""),
                    "topic": plan.get("selected_topic", ""),
                    "hashtags": copy.get("hashtags", []),
                    "published_at": publish_result.get("published_at", ""),
                    "status": publish_result.get("status", ""),
                    "content_type": plan.get("content_type", ""),
                    "style_id": visual_plan.get("style_id", ""),
                    "play_id": plan.get("play_id", ""),
                },
            )
        except Exception as e:
            logger.warning(f"记录发布历史失败: {e}")

    return {
        "publish_result": _with_publish_link_metadata(publish_result, state),
        "phase": WorkflowPhase.PUBLISHING,
        # Only present when this execution consumed an explicit force (F3):
        # the caller writes it back to state so the bypass never sticks.
        **({"publish_options": cleared_publish_options} if cleared_publish_options else {}),
    }
