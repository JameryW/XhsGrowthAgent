"""brief_content seam regressions (P1a-S4-3).

brief_content joins the Artifact Store registry: the body — dominated by the
raw_text payload — goes out-of-line, with **no routing meta**: no router reads
brief_content (the /status DB label reads the small brand/product fields, but
only after the hoisted /status resolve_state; every agent consumer hydrates
through the node seam on the way in). These tests pin:

- the registry wiring (REFABLE_FIELDS, deliberately absent from META_KEY_OF);
- refify externalizes a non-empty brief_content write and resolve round-trips
  the stored body for node/route consumers;
- a deliberate clear stays inline and tombstones the stale ref;
- store failure degrades to inline + tombstone (best-effort contract).
"""

from __future__ import annotations

import asyncio

from langgraph.store.memory import InMemoryStore

from backend.state.artifacts import META_KEY_OF, REFABLE_FIELDS, refify_updates, resolve_state


def test_registry_wiring():
    """brief_content is refable and carries no routing meta."""
    assert "brief_content" in REFABLE_FIELDS
    assert "brief_content" not in META_KEY_OF


def test_refify_externalizes_brief_content_and_resolve_roundtrips():
    store = InMemoryStore()
    body = {
        "raw_text": "新品上市 brief：主打便携风扇，卖点静音+续航，" * 20,
        "source_type": "text",
    }
    result = asyncio.run(refify_updates(store, "t1", {"brief_content": body}, prev_values={}))

    # Body out-of-line, only the ref stays in RuntimeState
    assert "brief_content" not in result
    assert result["artifacts"]["brief_content"]["ref"] == "artifact://brief_content/latest"

    # Stored body resolves back for node/route consumers
    values = {"artifacts": {"brief_content": result["artifacts"]["brief_content"]}}
    resolved = asyncio.run(resolve_state(store, "t1", values))
    assert resolved["brief_content"] == body


def test_refify_clear_tombstones_ref():
    store = InMemoryStore()
    seeded = asyncio.run(
        refify_updates(store, "t1", {"brief_content": {"raw_text": "旧 brief"}}, prev_values={})
    )
    assert "brief_content" not in seeded

    cleared = asyncio.run(refify_updates(store, "t1", {"brief_content": {}}, prev_values={}))

    # Deliberate clear: inline {} wins, stale ref tombstoned (no meta to reset).
    assert cleared["brief_content"] == {}
    assert cleared["artifacts"]["brief_content"] is None

    # The tombstone stops resolve_state from injecting the stale body.
    resolved = asyncio.run(resolve_state(store, "t1", {"artifacts": dict(cleared["artifacts"])}))
    assert "brief_content" not in resolved


def test_refify_without_store_degrades_inline():
    body = {"raw_text": "离线 brief", "source_type": "text"}
    result = asyncio.run(refify_updates(None, "t1", {"brief_content": body}, prev_values={}))

    # Best-effort contract: body stays inline, ref tombstoned so resolve_state
    # lets the inline value through everywhere.
    assert result["brief_content"] == body
    assert result["artifacts"]["brief_content"] is None
