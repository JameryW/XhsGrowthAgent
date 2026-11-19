"""PORT span learning: only repeated, explicit human edits are reused."""

from __future__ import annotations

from backend.services.port import (
    apply_port_memory,
    merge_port_memory,
    mine_span_revisions,
)


def test_mine_span_revisions_keeps_replacements_and_drops_insertions():
    spans = mine_span_revisions(
        "这个产品首先很好用，值得买。",
        "这个产品直接很好用，值得买。另外补充一句。",
    )

    assert [span.old for span in spans] == ["首先"]
    assert [span.new for span in spans] == ["直接"]


def test_merge_counts_support_and_apply_requires_two_confirmations():
    first = merge_port_memory([], mine_span_revisions("首先很好", "直接很好"))
    second = merge_port_memory(first, mine_span_revisions("首先很好", "直接很好"))

    assert second[0].support == 2
    result = apply_port_memory("这个首先很好用", [span.as_dict() for span in second])
    assert result.text == "这个直接很好用"
    assert len(result.applied) == 1


def test_apply_skips_single_observation_memory():
    once = merge_port_memory([], mine_span_revisions("首先很好", "直接很好"))

    result = apply_port_memory("这个首先很好用", [span.as_dict() for span in once])

    assert result.text == "这个首先很好用"
    assert result.applied == ()
