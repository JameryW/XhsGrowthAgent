"""P0 contract-equivalence tests (P1a-S4-4).

The S4 artifact seams move big bodies out of the checkpoint, but several P0
behaviors must stay byte-identical whether the content is inline (legacy) or
artifact-backed (ref'd). The seam-wrapped publisher node only ever sees the
RESOLVED view, so every hash/gate below is asserted twice: once over the
inline state (the pre-P1a shape) and once over the refify→resolve roundtrip
of the same content — the two verdicts must agree:

- publish_id (P0-W4 double-fire guard): the key hashes copy_content +
  visual_plan, both refable fields — a drifting hash on ref'd threads would
  silently re-arm the idempotency guard for already-published content.
- dry-run double check: state["dry_run"] OR publish_options["dry_run"] —
  both scalars must pass through resolve_state untouched and keep forcing
  the mock path on a resolved state.
- pause_reason / evaluation_result (P0-W5 fail-closed): the evaluator parks
  with pause_reason=evaluator_fail_closed and /resume demands an explicit
  human_decision; the quality-gate predicate must return the same verdict
  on the resolved view, and the contract fields must stay registry-exempt.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from backend.agents.publisher import PublisherAgent, compute_publish_id
from backend.config.settings import Settings
from backend.graph.routers import evaluator_requires_human
from backend.state.artifacts import REFABLE_FIELDS, refify_updates, resolve_state

_CONTRACT_SCALARS = ("dry_run", "pause_reason", "publish_options", "evaluation_result")


def _content() -> tuple[dict, dict]:
    copy = {
        "selected_title": "夏日便携风扇测评",
        "body_text": "正文内容" * 50,
        "hashtags": ["数码", "好物"],
        "cta": "评论区聊聊",
    }
    # image paths deliberately unsorted — compute_publish_id sorts them.
    visual = {"image_paths": ["/tmp/b.png", "/tmp/a.png"], "color_palette": ["#ffffff"]}
    return copy, visual


@pytest.mark.asyncio
async def test_publish_id_resolved_view_matches_inline_view():
    """The double-fire guard key over the RESOLVED view equals the inline key.

    This is the prd's 双跑断言同值: hash(inline state) == hash(artifact-backed
    state after the refify→resolve roundtrip). Time is frozen so the window
    bucket cannot straddle a boundary between the two hash calls.
    """
    store = InMemoryStore()
    copy, visual = _content()
    inline_state = {
        "copy_content": copy,
        "visual_plan": visual,
        "account_id": "acc1",
        "session_id": "t1",
        "publish_options": {},
    }

    with patch("time.time", return_value=1_000_000_000.0):
        inline_id = compute_publish_id(inline_state)

    refified = await refify_updates(
        store, "t1", {"copy_content": copy, "visual_plan": visual}, prev_values={}
    )
    assert "copy_content" not in refified
    assert "visual_plan" not in refified
    refd_state = {**inline_state, **refified}
    resolved = await resolve_state(store, "t1", refd_state)

    # The roundtrip restored the exact bodies the hash consumes.
    assert resolved["copy_content"] == copy
    assert resolved["visual_plan"] == visual

    with patch("time.time", return_value=1_000_000_000.0):
        resolved_id = compute_publish_id(resolved)
    assert resolved_id == inline_id


@pytest.mark.asyncio
async def test_publish_id_stable_across_node_reexecution():
    """A node re-run re-externalizes identical bodies — the key must not drift.

    The seam rewrites the update on EVERY node execution; the idempotency
    record was filed under the first execution's key, so a re-execution (and
    any /publish-retry) must recompute the same key from the re-stored body.
    """
    store = InMemoryStore()
    copy, visual = _content()

    with patch("time.time", return_value=1_000_000_000.0):
        first = compute_publish_id(
            {"copy_content": copy, "visual_plan": visual, "account_id": "acc1"}
        )

    # Second execution: same bodies re-refified into the same store slot; the
    # checkpoint-side scalars (account_id) survive alongside the refs.
    await refify_updates(store, "t1", {"copy_content": copy, "visual_plan": visual}, prev_values={})
    refified = await refify_updates(
        store, "t1", {"copy_content": copy, "visual_plan": visual}, prev_values={}
    )
    resolved = await resolve_state(store, "t1", {"account_id": "acc1", **refified})

    with patch("time.time", return_value=1_000_000_000.0):
        second = compute_publish_id(resolved)
    assert second == first


@pytest.mark.asyncio
async def test_contract_scalars_stay_registry_exempt_and_passthrough():
    """The fail-closed/dry-run contract fields are never refable, and resolve
    returns them byte-identical on a ref'd thread."""
    for key in _CONTRACT_SCALARS:
        assert key not in REFABLE_FIELDS, key

    store = InMemoryStore()
    copy, _ = _content()
    refified = await refify_updates(store, "t1", {"copy_content": copy}, prev_values={})
    evaluation = {"decision": "approved", "dimensions": [{"dimension": "quality"}]}
    state = {
        "session_id": "t1",
        "account_id": "acc1",
        "phase": "publishing",
        "dry_run": True,
        "pause_reason": "evaluator_fail_closed",
        "publish_options": {"dry_run": False, "account_id": "acc1"},
        "evaluation_result": evaluation,
        "revision_count": 0,
        **refified,
    }

    resolved = await resolve_state(store, "t1", state)

    assert resolved["dry_run"] is True
    assert resolved["pause_reason"] == "evaluator_fail_closed"
    assert resolved["publish_options"] == {"dry_run": False, "account_id": "acc1"}
    assert resolved["evaluation_result"] == evaluation
    # ...while the ref'd body is hydrated back.
    assert resolved["copy_content"] == copy


@pytest.mark.asyncio
async def test_dry_run_double_check_identical_on_resolved_state():
    """The defense-in-depth dry-run gate fires identically on both shapes.

    Workflow-level dry_run=True must take the mock path even when
    publish_options.dry_run=False (the approve-decision cannot silently flip
    it), and the mock result must equal the inline-state result.
    """
    store = InMemoryStore()
    copy, visual = _content()
    inline_state = {
        "session_id": "t1",
        "account_id": "acc1",
        "dry_run": True,
        "publish_options": {"dry_run": False},
        "copy_content": copy,
        "visual_plan": visual,
    }
    refified = await refify_updates(
        store, "t1", {"copy_content": copy, "visual_plan": visual}, prev_values={}
    )
    resolved_state = await resolve_state(store, "t1", {**inline_state, **refified})

    fake_settings = MagicMock()
    fake_settings.platform.use_browser = True
    agent = PublisherAgent()
    with patch("backend.config.settings.Settings", lambda: fake_settings):
        from_inline = await agent.execute(inline_state, store)
        from_resolved = await agent.execute(resolved_state, store)

    for result in (from_inline, from_resolved):
        assert result["publish_result"]["status"] == "mock_published"
        assert result["phase"].value == "publishing"
    # published_at is a timestamp — compare the deterministic identity fields.
    for key in ("post_id", "post_url", "status", "workflow_thread_id", "platform_post_id"):
        assert from_resolved["publish_result"][key] == from_inline["publish_result"][key], key


@pytest.mark.asyncio
async def test_quality_gate_predicate_identical_on_resolved_state():
    """evaluator_requires_human returns the same verdict on both shapes.

    evaluation_result stays inline (registry-exempt), so the resolved view is
    byte-identical for the predicate — pinned here for every fail-closed
    family: degraded evidence, compliance-driven rejection at the revision
    ceiling, and the plain quality track that must NOT demand a human.
    """
    store = InMemoryStore()
    copy, visual = _content()
    refified = await refify_updates(
        store, "t1", {"copy_content": copy, "visual_plan": visual}, prev_values={}
    )
    max_revisions = Settings().workflow.max_revision_count

    shapes = [
        # approved → no human needed
        ({"decision": "approved"}, 0, False),
        # degraded evidence (LLM timeout / empty result) → fail closed
        ({"decision": "approved", "degraded": True}, 0, True),
        ({"decision": None}, 0, True),
        # compliance-driven rejection at the revision ceiling → fail closed
        ({"decision": "rejected", "failed_dimensions": ["compliance"]}, max_revisions, True),
        # blocking evidence on ANY track at the ceiling → fail closed (the
        # is_blocking dimension marker, not the dimension name, is the signal)
        (
            {
                "decision": "rejected",
                "failed_dimensions": ["accuracy"],
                "dimensions": [{"dimension": "accuracy", "is_blocking": True}],
            },
            max_revisions,
            True,
        ),
        # plain quality rejection → the revise loop, not the human channel
        ({"decision": "rejected", "failed_dimensions": ["quality"]}, max_revisions, False),
        ({"decision": "needs_revision"}, max_revisions, False),
    ]

    for evaluation, revision_count, expected in shapes:
        inline_state = {
            "session_id": "t1",
            "evaluation_result": evaluation,
            "revision_count": revision_count,
        }
        resolved_state = await resolve_state(store, "t1", {**inline_state, **refified})

        assert evaluator_requires_human(inline_state) is expected, evaluation
        assert evaluator_requires_human(resolved_state) is expected, evaluation
