"""trend_data seam regressions (P1a-S4-1).

trend_data joins the Artifact Store registry: the body goes out-of-line and a
small ``trend_summary`` meta stays in RuntimeState so the ``should_plan``
router — which sees raw checkpoint state and never the store — keeps deciding
on actionable-topic truthiness. These tests pin:

- refify externalizes a non-empty trend_data write and derives the meta;
- a deliberate clear stays inline, tombstones the stale ref, resets the meta;
- store failure degrades to inline + tombstone with the meta still derived
  (routers stay correct on the fallback path);
- resolve_state round-trips the stored body for node/route consumers;
- trend_summary_of mirrors should_plan's exact alias chain;
- the registry wiring (REFABLE_FIELDS / META_KEY_OF).
"""

from __future__ import annotations

import asyncio

from langgraph.store.memory import InMemoryStore

from backend.state.artifacts import (
    META_KEY_OF,
    REFABLE_FIELDS,
    refify_updates,
    resolve_state,
    trend_summary_of,
)


def test_registry_wiring():
    """trend_data is refable and its meta key is declared."""
    assert "trend_data" in REFABLE_FIELDS
    assert META_KEY_OF["trend_data"] == "trend_summary"


def test_refify_externalizes_trend_data_and_derives_meta():
    store = InMemoryStore()
    body = {
        "hot_topics": [{"topic": "探店"}, {"topic": "穿搭"}],
        "trending_keywords": ["美食", "咖啡"],
    }
    result = asyncio.run(refify_updates(store, "t1", {"trend_data": body}, prev_values={}))

    # Body out-of-line, ref + meta kept in RuntimeState
    assert "trend_data" not in result
    assert result["artifacts"]["trend_data"]["ref"] == "artifact://trend_data/latest"
    assert result["trend_summary"] == {"has_topics": True, "hot_topic_count": 2}

    # Stored body resolves back for node/route consumers
    values = {"artifacts": {"trend_data": result["artifacts"]["trend_data"]}}
    resolved = asyncio.run(resolve_state(store, "t1", values))
    assert resolved["trend_data"] == body


def test_refify_clear_tombstones_ref_and_resets_meta():
    store = InMemoryStore()
    seeded = asyncio.run(
        refify_updates(store, "t1", {"trend_data": {"hot_topics": ["旧话题"]}}, prev_values={})
    )
    assert seeded["trend_summary"] == {"has_topics": True, "hot_topic_count": 1}

    cleared = asyncio.run(refify_updates(store, "t1", {"trend_data": {}}, prev_values={}))

    # Deliberate clear: inline {} wins, stale ref tombstoned, meta reset.
    assert cleared["trend_data"] == {}
    assert cleared["artifacts"]["trend_data"] is None
    assert cleared["trend_summary"] == {"has_topics": False, "hot_topic_count": 0}

    # The tombstone stops resolve_state from injecting the stale body.
    resolved = asyncio.run(resolve_state(store, "t1", {"artifacts": dict(cleared["artifacts"])}))
    assert "trend_data" not in resolved


def test_refify_without_store_degrades_inline_and_still_derives_meta():
    result = asyncio.run(
        refify_updates(None, "t1", {"trend_data": {"trending_topics": ["穿搭"]}}, prev_values={})
    )

    # Best-effort contract: body stays inline, ref tombstoned, meta derived
    # store-independently so the router stays correct on the inline path.
    assert result["trend_data"] == {"trending_topics": ["穿搭"]}
    assert result["artifacts"]["trend_data"] is None
    assert result["trend_summary"] == {"has_topics": True, "hot_topic_count": 1}


def test_trend_summary_of_mirrors_router_alias_chain():
    assert trend_summary_of({"hot_topics": ["a", "b"]}) == {
        "has_topics": True,
        "hot_topic_count": 2,
    }
    # Alias chain: trending_topics/topics count when hot_topics is absent.
    assert trend_summary_of({"trending_topics": ["a"]})["has_topics"] is True
    assert trend_summary_of({"topics": ["a", "b", "c"]})["hot_topic_count"] == 3
    # Empty / garbage shapes
    assert trend_summary_of({}) == {"has_topics": False, "hot_topic_count": 0}
    assert trend_summary_of({"hot_topics": []}) == {"has_topics": False, "hot_topic_count": 0}
    assert trend_summary_of(None) == {"has_topics": False, "hot_topic_count": 0}
    assert trend_summary_of("not-a-dict") == {"has_topics": False, "hot_topic_count": 0}
