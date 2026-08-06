"""Unit tests for manual-only xhs engagement tools.

Relocated from ``tests/unit/tools/test_llm_tools.py`` when the 4 dead LLM
tools (title_generator / hashtag_researcher / image_prompt_generator /
timing_optimizer) and their sole test file were deleted. This test verifies
the manual-only interaction tools remain importable for explicit operator
use — it is unrelated to the deleted LLM tools and must be preserved.
"""

from backend.tools.xhs import (
    comment_replier,
    dm_handler,
    escalation_flagger,
    fetch_pending_comments,
)


def test_manual_engagement_tools_remain_importable():
    """Manual-only interaction tools remain available for explicit operator use."""
    tools = (comment_replier, dm_handler, escalation_flagger, fetch_pending_comments)

    assert {tool.name for tool in tools} == {
        "comment_replier",
        "dm_handler",
        "escalation_flagger",
        "fetch_pending_comments",
    }
    assert all("manual-only" in tool.description for tool in tools)
