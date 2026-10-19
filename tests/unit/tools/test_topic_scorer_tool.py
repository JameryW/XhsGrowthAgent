"""``analysis.topic_scorer`` — its credential, and its refusal to invent a score.

Two defects are pinned here, because they were the same lie told twice:

1. The tool built ``XHSClient()`` with no cookie, so it read the platform as
   nobody — every call raised, while the capability declared
   ``auth_scope=("xhs:read",)``, a grant nothing could satisfy.
2. Its ``except`` answered that failure with ``heat_score=50``, which the caller
   wrote into a prompt as if it had been measured.

So the assertions are: the credential reaches the client, a missing one raises,
and a read failure **escapes** rather than becoming a number.
"""

from __future__ import annotations

import pytest

from backend.services.xhs_client import XHSAuthError
from backend.tools.analysis.topic_scorer import topic_scorer

COOKIE = "a1=" + "0" * 20 + "; web_session=session"


class _Post:
    def __init__(self, likes: int, comments: int, note_id: str = "n1") -> None:
        self.likes = likes
        self.comments = comments
        self.note_id = note_id
        self.title = "标题"
        self.note_url = "https://x/n1"


class _Client:
    """A stand-in with the two reads the scorer makes, and nothing else."""

    def __init__(
        self,
        *,
        posts=None,
        keyword_rows=None,
        boom: Exception | None = None,
        readable: bool = True,
    ) -> None:
        self.can_read = readable
        self.cookie = ""
        self.user_id = ""
        self.account_id = ""
        self.closed = False
        self._posts = posts if posts is not None else [_Post(120, 40), _Post(80, 10, "n2")]
        self._keyword_rows = keyword_rows or [{"keyword": "露营", "avg_likes": 300}]
        self._boom = boom

    async def search_posts(self, keyword: str, limit: int = 50):
        if self._boom is not None:
            raise self._boom
        return self._posts

    async def monitor_keywords(self, keywords: list[str]):
        if self._boom is not None:
            raise self._boom
        return self._keyword_rows

    async def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, client: _Client) -> _Client:
    async def _factory(account_id: str = "") -> _Client:
        client.account_id = account_id
        return client

    monkeypatch.setattr("backend.services.xhs_client.client_for_account", _factory)
    return client


@pytest.mark.asyncio
async def test_it_reads_as_the_account_it_was_given(monkeypatch):
    client = _patch_client(monkeypatch, _Client())

    await topic_scorer.ainvoke({"topic": "露营", "niche": "旅行", "account_id": "acc-7"})

    assert client.account_id == "acc-7"


@pytest.mark.asyncio
async def test_no_credential_raises_instead_of_scoring_a_guess(monkeypatch):
    """An unreadable platform is not a topic with a middling score."""
    client = _patch_client(monkeypatch, _Client(readable=False))

    with pytest.raises(XHSAuthError):
        await topic_scorer.ainvoke({"topic": "露营", "niche": "旅行"})

    assert client.closed is True


@pytest.mark.asyncio
async def test_a_read_failure_escapes_instead_of_becoming_a_number(monkeypatch):
    """The removed ``except`` used to answer this with ``heat_score=50``.

    Letting it out is what lets the Gateway file ``ToolResult(ok=False)``; the
    caller then skips the topic.  A dict here would be a measurement nobody made.
    """
    _patch_client(monkeypatch, _Client(boom=RuntimeError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        await topic_scorer.ainvoke({"topic": "露营", "niche": "旅行"})


@pytest.mark.asyncio
async def test_a_real_read_still_produces_a_score(monkeypatch):
    """The guard must not turn "works fine" into "never readable"."""
    _patch_client(monkeypatch, _Client())

    result = await topic_scorer.ainvoke({"topic": "露营", "niche": "旅行"})

    assert isinstance(result, dict)
    assert result["topic"] == "露营"
    assert result["heat_score"] > 50  # 2 posts + interactions + keyword + niche
    assert result["data_metrics"]["post_count"] == 2
    assert [p["note_id"] for p in result["reference_posts"]]
    assert "error" not in result
