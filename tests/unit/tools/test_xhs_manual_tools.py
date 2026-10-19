"""Unit tests for manual-only xhs engagement tools.

Relocated from ``tests/unit/tools/test_llm_tools.py`` when the 4 dead LLM
tools (title_generator / hashtag_researcher / image_prompt_generator /
timing_optimizer) and their sole test file were deleted. This test verifies
the manual-only interaction tools remain importable for explicit operator
use — it is unrelated to the deleted LLM tools and must be preserved.

``fetch_pending_comments`` used to be a tool that **could not succeed**: it
built ``XHSClient()`` with no cookie, so ``can_read`` was always ``False``, and
``get_comments`` answers that precondition with ``[]`` instead of raising. The
tool then caught everything anyway. Net effect: a moderation queue that always
said "nothing to review" without reading anything. The tests below pin the
replacement contract — empty means empty, and everything else is an exception.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.services import xhs_client as xhs_client_module
from backend.services.xhs_client import XHSAuthError
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


class _Client:
    """A client double: reads need ``can_read``, and nothing else is faked."""

    def __init__(
        self,
        *,
        can_read: bool = True,
        rows: list[Any] | None = None,
        fails_with: Exception | None = None,
    ) -> None:
        self.can_read = can_read
        self._rows = rows or []
        self._fails_with = fails_with
        self.closed = False
        self.asked: list[tuple[str, int]] = []

    async def get_comments(self, post_id: str, limit: int = 20) -> list[Any]:
        self.asked.append((post_id, limit))
        if self._fails_with is not None:
            raise self._fails_with
        return list(self._rows)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture()
def resolve(monkeypatch: pytest.MonkeyPatch):
    """Point the tool's client factory at a double, recording the account asked for."""
    asked: list[str] = []

    def install(client: _Client) -> list[str]:
        async def _factory(account_id: str = "") -> _Client:
            asked.append(account_id)
            return client

        # The tool imports the factory inside its body, from this module, so
        # patching the module attribute is what the import actually resolves.
        monkeypatch.setattr(xhs_client_module, "client_for_account", _factory)
        return asked

    return install


class _Row:
    """Just enough shape for the dict comprehension."""

    comment_id = "c1"
    post_id = "p1"
    user_name = "someone"
    user_id = "u1"
    content = "how much?"
    like_count = 3
    created_at = "2026-10-19"


class TestTheModerationQueueRefusesToSayEmpty:
    async def test_no_credential_raises_before_touching_the_platform(self, resolve):
        client = _Client(can_read=False)
        resolve(client)

        with pytest.raises(XHSAuthError):
            await fetch_pending_comments.coroutine(post_id="p1")

        assert client.asked == [], "the tool must not read without an identity"
        assert client.closed is True, "the client is closed even on refusal"

    async def test_a_read_failure_propagates_instead_of_becoming_an_empty_queue(self, resolve):
        client = _Client(fails_with=RuntimeError("boom"))
        resolve(client)

        with pytest.raises(RuntimeError):
            await fetch_pending_comments.coroutine(post_id="p1")

        assert client.asked == [("p1", 20)]
        assert client.closed is True

    async def test_an_empty_read_is_still_an_empty_list(self, resolve):
        client = _Client(rows=[])
        resolve(client)

        assert await fetch_pending_comments.coroutine(post_id="p1") == []

    async def test_the_account_travels_to_the_client(self, resolve):
        asked = resolve(_Client(rows=[_Row()]))

        rows = await fetch_pending_comments.coroutine(post_id="p1", account_id="acc-7")

        assert asked == ["acc-7"], "a named account must be read as itself"
        assert rows == [
            {
                "comment_id": "c1",
                "post_id": "p1",
                "user_name": "someone",
                "user_id": "u1",
                "content": "how much?",
                "like_count": 3,
                "created_at": "2026-10-19",
            }
        ]
