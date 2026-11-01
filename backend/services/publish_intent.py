"""The mainline's side of the control-plane migration — P1 first slice (票 5ba).

P1 of ``docs/publish-action-protocol.md`` asks the mainline publish to stop being
an unstructured ``run_publish`` call.  The full slice needs an identity the
mainline does not have yet — ``ActionIntent`` requires ``creator_id`` /
``audience_id`` / ``decision_id``, and a ``DecisionRecord`` is a creator-agent
concept (it needs an audience and a model revision).  Inventing those is exactly
what the plan forbids, so P1 is split: this module lands the half that can be
*derived* without inventing anything.

What it derives, and why each derivation is honest:

* **who is publishing** — a named account, or explicitly the deployment itself.
  The mainline's actor has always been ``publish_options["account_id"]``;
  ``state["account_id"]`` is a workflow label, not a validated actor.  A blank
  value means the deployment principal, which is the same identity
  ``services.xhs_credentials`` resolves from the deployment's own cookie/CDP
  declaration — it is a real principal, not an invented account.
* **what is being published** — the copy/visual bodies as an artifact
  (``artifact://publish_content/<publish_id>``) plus its sha256.  That pair is
  what a durable publish intent carries; hashing the body the publish will
  submit keeps the fingerprint attached to the content, not to the request.

Nothing in this module submits, authorizes, or decides.  It is data derivation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

    from backend.state.artifacts import ArtifactRef

__all__ = [
    "PUBLISH_CONTENT_KIND",
    "PublishIntentMaterial",
    "PublishPrincipal",
    "publish_content_body",
    "publish_intent_material",
    "resolve_publish_principal",
    "write_publish_content_artifact",
]

#: Artifact kind for the submitted content: ``artifact://publish_content/<publish_id>``.
PUBLISH_CONTENT_KIND = "publish_content"


@dataclass(frozen=True)
class PublishPrincipal:
    """Who a publish acts as; ``deployment`` means "no account was named"."""

    kind: Literal["account", "deployment"]
    account_id: str

    @property
    def is_account(self) -> bool:
        return self.kind == "account"


@dataclass(frozen=True)
class PublishIntentMaterial:
    """The derivable half of a publish intent (票 5ba).

    Empty ``artifact_ref`` / ``content_hash`` mean "not stored" — the caller
    keeps the record's fields empty rather than pointing at a missing body.
    """

    principal: PublishPrincipal
    artifact_ref: str = ""
    content_hash: str = ""


def resolve_publish_principal(
    publish_options: Mapping[str, Any] | None,
) -> PublishPrincipal:
    """Classify the publishing principal from the caller's ``publish_options``.

    A blank or absent ``account_id`` is the **deployment** principal, never an
    invented account: the credential resolver reads the deployment's own
    declaration for it, and a workflow's ``state["account_id"]`` label is not a
    validated actor (the publish path has always said so).
    """
    named = str((publish_options or {}).get("account_id") or "").strip()
    if named:
        return PublishPrincipal(kind="account", account_id=named)
    return PublishPrincipal(kind="deployment", account_id="")


def publish_content_body(state: Mapping[str, Any]) -> dict[str, Any]:
    """The exact content a publish submits, in one canonical, hashable shape.

    Only content the submit action actually uses is included, so the hash moves
    when (and only when) what would be posted moves.  Missing/None sub-bodies
    yield empty values instead of keys disappearing — the shape is stable, which
    is what makes the hash comparable across calls.
    """
    copy = state.get("copy_content") or {}
    visual = state.get("visual_plan") or {}
    hashtags = copy.get("hashtags") or []
    images = visual.get("image_paths") or []
    return {
        "title": str(copy.get("selected_title") or ""),
        "body": str(copy.get("body_text") or ""),
        "hashtags": [str(tag) for tag in hashtags],
        "image_paths": [str(path) for path in images],
    }


async def write_publish_content_artifact(
    store: BaseStore | None,
    thread_id: str,
    publish_id: str,
    state: Mapping[str, Any],
) -> ArtifactRef | None:
    """Store the publish content under ``artifact://publish_content/<publish_id>``.

    Best-effort by the Artifact Store's own contract: returns ``None`` when the
    write cannot happen (no store / thread / publish id, or storage failure).
    """
    if store is None or not thread_id or not publish_id:
        return None
    from backend.state.artifacts import put_artifact

    return await put_artifact(
        store,
        thread_id,
        PUBLISH_CONTENT_KIND,
        publish_content_body(state),
        kind=PUBLISH_CONTENT_KIND,
        artifact_id=publish_id,
    )


async def publish_intent_material(
    store: BaseStore | None,
    thread_id: str,
    publish_id: str,
    state: Mapping[str, Any],
    *,
    principal: PublishPrincipal | None = None,
) -> PublishIntentMaterial:
    """Principal + content artifact/hash for one publish, as intent-shaped data.

    Never raises on a storage failure and never changes publish behaviour: the
    fields stay empty and the caller proceeds exactly as before.  ``principal``
    can be passed when the caller already classified it (the publish path does,
    once, instead of re-deriving the same value).
    """
    resolved = principal or resolve_publish_principal(state.get("publish_options"))
    ref = await write_publish_content_artifact(store, thread_id, publish_id, state)
    if ref is None:
        return PublishIntentMaterial(principal=resolved)
    return PublishIntentMaterial(
        principal=resolved,
        artifact_ref=str(ref.get("ref") or ""),
        content_hash=str(ref.get("content_hash") or ""),
    )
