"""Publish execution — the Action Executor's one side-effecting path (P2a-S3).

S1 gave the protocol a ``PUBLISH`` capability and S2 gave it a policy gate;
neither produced an external effect.  This module is where a confirmed intent
finally reaches the platform.  Three constraints, each inherited from a
neighbouring slice, shape it:

* **The executor stays deterministic from the immutable intent.**  Everything a
  publish needs is read off the intent (account, artifact ref, content hash,
  idempotency key, thread) or off the artifact it points at — never off an
  execution-time argument.  That is what makes a receipt a statement about
  *that* intent rather than about whoever happened to call execute.

* **Side effects go through the Tool Gateway, by name.**  ``xhs.publish`` is
  invoked as a capability; this module never imports the tool.  Implementations
  are resolved per call (``catalog.bind``), so a test that rebinds the tool
  module attribute is honoured — which is the only reason a test can run this
  very code path instead of a paraphrase of it.

* **Every seam is injectable, and every default is the real thing.**  A
  dispatcher (the Gateway call), a content reader (the Artifact Store fetch)
  and a scope resolver (the account's credential, P2a-S5a).  The defaults are
  resolved lazily so that injecting a substitute does not quietly replace the
  production path everywhere else; the module's tests prove the default
  dispatcher really is the shared Gateway, and the default reader really is the
  Artifact Store façade.

Deliberately *not* here: cool-down bookkeeping.  ``note_publish`` belongs to
the layer that owns the publish event — ``services.xhs_publisher`` already
writes it.  Recording it here as well would give one event two writers and two
definitions of "counts as a publish attempt".

Also deliberately *not* here: retry.  The Gateway can retry a capability only
when its payload carries an idempotency key; the key is now wired, but a
*publish* also needs "did the submit already happen?" to be answerable before a
second attempt is safe, and a Gateway-level timeout cannot answer it.  See
``backend/tools/runtime/catalog.py`` for where that is written down.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from backend.tools.runtime.models import ErrorKind, ToolResult

__all__ = [
    "PUBLISH_CAPABILITY",
    "PublishContent",
    "PublishContentReader",
    "PublishDispatcher",
    "PublishOutcome",
    "PublishRequest",
    "PublishStatus",
    "ScopeResolver",
    "artifact_store_content_reader",
    "build_publish_payload",
    "content_hash_of",
    "gateway_publish_dispatcher",
    "interpret_publish_result",
    "load_publish_content",
]

#: The capability the executor publishes through.  A dotted name, not a module
#: path: the runtime resolves it per call.
PUBLISH_CAPABILITY = "xhs.publish"

# The platform layer's own status vocabulary (``services.xhs_publisher``
# P0-W4): ``published`` is the only success; ``unknown``/``pending`` mean "a
# submit was issued and the outcome is not known", which is *not* a failure and
# must never be treated as one — the service's contract says so explicitly.
_PUBLISHED_STATUSES = frozenset({"published"})
_AMBIGUOUS_STATUSES = frozenset({"unknown", "pending"})


class PublishStatus(StrEnum):
    """What one publish attempt resolved to, from the caller's side."""

    PUBLISHED = "published"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PublishContent:
    """The publishable body of one artifact."""

    title: str
    body: str
    hashtags: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()
    category: str = ""
    location: str = ""


@dataclass(frozen=True)
class PublishRequest:
    """Everything one publish needs, and nothing the caller can improvise."""

    account_id: str
    thread_id: str
    idempotency_key: str
    artifact_ref: str
    content_hash: str
    content: PublishContent


@dataclass(frozen=True)
class PublishOutcome:
    """The result of one publish attempt."""

    status: PublishStatus
    note_id: str = ""
    note_url: str = ""
    error: str = ""
    retry_after_seconds: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is PublishStatus.PUBLISHED


class PublishDispatcher(Protocol):
    """Where a publish request goes.  The seam, not an implementation."""

    def __call__(self, request: PublishRequest) -> Awaitable[PublishOutcome]: ...


class PublishContentReader(Protocol):
    """How an artifact ref becomes a body.  The other seam."""

    def __call__(self, *, thread_id: str, artifact_ref: str) -> Awaitable[Any | None]: ...


def _as_text(value: Any) -> str:
    """Blank-safe text: ``None`` → ``""``, everything else through ``str``."""
    return "" if value is None else str(value).strip()


def _as_str_list(value: Any) -> list[str]:
    """A list of non-blank strings from an unknown shape.

    A bare string becomes a single element rather than being iterated — the
    same rule ``backend/models/outputs.py`` applies to hashtags, and for the
    same reason: iterating ``"a、b"`` produces a character list that *looks*
    like a successful parse.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [text for item in value if (text := _as_text(item))]
    text = _as_text(value)
    return [text] if text else []


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_publish_content(body: Any) -> PublishContent | None:
    """Read the publish payload out of an artifact body, or ``None`` if unusable.

    The body contract is the tool's own argument set, because that is what the
    artifact has to become.  A missing title or body is *unusable* rather than
    defaulted: posting an untitled note to a real account is not something to
    paper over with ``""``, and the caller turns this ``None`` into a refusal
    that happens before any side effect.
    """
    if not isinstance(body, Mapping):
        return None
    title = _as_text(body.get("title"))
    text = _as_text(body.get("body"))
    if not title or not text:
        return None
    return PublishContent(
        title=title,
        body=text,
        hashtags=tuple(_as_str_list(body.get("hashtags"))),
        image_paths=tuple(_as_str_list(body.get("image_paths"))),
        category=_as_text(body.get("category")),
        location=_as_text(body.get("location")),
    )


def build_publish_payload(request: PublishRequest) -> Mapping[str, Any]:
    """The Gateway payload for one publish.

    Two keys are here for reasons that are not about the platform call:

    * ``idempotency_key`` — the Gateway refuses to retry a side-effecting
      capability whose payload lacks it, and names that refusal in the error.
      Passing it is what makes the capability *retryable in principle*; whether
      retrying is currently safe is a separate question, answered in the
      catalogue.
    * ``account_id`` — threaded down to the platform layer so that the risk
      gate records the attempt against the **account** rather than the CDP
      endpoint.  Without it the account-keyed publish cool-down has no writer
      at all in production (P2a-S2 pinned that gap; this is where it closes).
    """
    return {
        "title": request.content.title,
        "body": request.content.body,
        "hashtags": list(request.content.hashtags),
        "image_paths": list(request.content.image_paths),
        "category": request.content.category,
        "location": request.content.location,
        "account_id": request.account_id,
        "idempotency_key": request.idempotency_key,
    }


def interpret_publish_result(result: ToolResult) -> PublishOutcome:
    """Map one Gateway result onto the publish vocabulary.

    One mapping site on purpose: the Gateway speaks ``ok`` / ``error_kind`` and
    the platform speaks ``status`` / ``result_known``, and any second place that
    reads both will eventually disagree with this one.

    A *domain outcome* is the platform's answer — it carries the fields the
    caller needs (``status``, ``error``, ``retry_after_seconds``) in its
    payload.  Everything else is the runtime's answer: a timeout or an
    exception, i.e. no answer at all.
    """
    if result.ok:
        value = result.value if isinstance(result.value, Mapping) else {}
        return _outcome_from_status(value)

    if result.error_kind is ErrorKind.DOMAIN:
        return _outcome_from_status(result.domain)

    return PublishOutcome(
        status=PublishStatus.FAILED,
        error=result.error or f"publish failed ({result.error_kind})",
    )


def _outcome_from_status(payload: Mapping[str, Any]) -> PublishOutcome:
    status = _as_text(payload.get("status"))
    error = _as_text(payload.get("error"))
    retry_after = _as_int(payload.get("retry_after_seconds"))
    if status in _PUBLISHED_STATUSES:
        return PublishOutcome(
            status=PublishStatus.PUBLISHED,
            note_id=_as_text(payload.get("post_id")),
            note_url=_as_text(payload.get("post_url")),
        )
    if status in _AMBIGUOUS_STATUSES:
        # Not a failure: a submit went out and the answer was lost.  Reported as
        # its own status so nothing downstream reads it as "safe to re-run".
        return PublishOutcome(
            status=PublishStatus.UNKNOWN,
            error=error or "publish submitted, outcome unknown",
            retry_after_seconds=retry_after,
        )
    return PublishOutcome(
        status=PublishStatus.FAILED,
        error=error or "publish did not report success",
        retry_after_seconds=retry_after,
    )


def content_hash_of(body: Any) -> str:
    """The Artifact Store's own content hash for a body.

    Lazily imported for the same reason as the reader below, and used for one
    thing: proving that the body about to be posted is the body the human
    confirmed.  ``make_ref`` hashes the same canonical rendering, so a ref's
    ``content_hash`` and this function agree by construction rather than by
    convention.
    """
    from backend.state.artifacts import content_hash

    return content_hash(body)


def artifact_store_content_reader(store: Any | None) -> PublishContentReader:
    """The default content reader: the Artifact Store façade.

    Lazily imported so that this module (which the executor always imports)
    stays off the ``langgraph.store`` import chain unless a publish actually
    runs — the same reason ``backend/state/artifacts.py`` keeps its ``BaseStore``
    import at module level but its consumers defer theirs.
    """

    async def _read(*, thread_id: str, artifact_ref: str) -> Any | None:
        from backend.state.artifacts import get_artifact_body

        return await get_artifact_body(store, thread_id, artifact_ref)

    return _read


def gateway_publish_dispatcher(
    gateway: Any | None = None,
    *,
    granted_scopes: tuple[str, ...] | None = None,
    scope_resolver: ScopeResolver | None = None,
) -> PublishDispatcher:
    """The default dispatcher: one Gateway invocation of ``xhs.publish``.

    ``granted_scopes`` is an explicit override for a caller that already holds
    the answer.  Left at ``None``, the scopes are resolved per request from the
    intent's account through ``services/xhs_credentials`` — which is what stops
    ``xhs.publish``'s declared ``auth_scope`` from being decorative.  S3 passed
    ``None`` because "nothing in this repo owns a publish grant yet" and the
    Gateway reads ``None`` as *unchecked*; an unchecked requirement is
    indistinguishable from no requirement, which is exactly the state P2a-S5a
    ends.

    The refusal is not here.  It lives one layer up in
    ``CreatorAdvisor._execute_publish``, before this function is reached: a
    Gateway scope violation *raises* by design (a missing grant is a wiring
    error there), while a caller asking about its own account deserves a typed
    answer — a receipt-less 409 that names the account.  Both layers read the
    same rule, so the executor's precondition and the runtime's requirement
    cannot disagree.
    """

    async def _dispatch(request: PublishRequest) -> PublishOutcome:
        from backend.services.xhs_credentials import granted_scopes as resolve_scopes
        from backend.tools.runtime.bridge import shared_gateway

        target = gateway if gateway is not None else shared_gateway()
        scopes = granted_scopes
        if scopes is None:
            scopes = await (scope_resolver or resolve_scopes)(request.account_id)
        result = await target.invoke(
            PUBLISH_CAPABILITY,
            build_publish_payload(request),
            thread_id=request.thread_id,
            granted_scopes=scopes,
        )
        return interpret_publish_result(result)

    return _dispatch


# A ``Callable`` alias kept next to the Protocol so type annotations stay short
# where the executor stores the seam.
Dispatcher = Callable[[PublishRequest], Awaitable[PublishOutcome]]

ScopeResolver = Callable[[str], Awaitable[tuple[str, ...]]]
"""How the scopes an account holds are resolved (injectable seam).

The default is the real owner of that answer
(``services.xhs_credentials.granted_scopes``); the seam exists so a test can
grant an account a credential without a credential store, not so a caller can
skip the rule.
"""
