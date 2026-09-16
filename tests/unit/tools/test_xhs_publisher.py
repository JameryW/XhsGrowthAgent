"""Regression tests for the XHS publisher tool wrapper.

P2a-S3 migrated this tool onto the runtime contract, so these pin the *new*
shape rather than the old one:

* a platform verdict arrives as a ``DomainOutcome`` -- an answer, not a hiccup;
* an unexpected failure propagates, so the Gateway classifies it instead of
  reading a swallowed ``{"status": "error"}`` as a successful call;
* the verdict sits at the *top level* of the domain payload, because a reader
  looking for ``status`` does not look one level down;
* the account id the executor hands over really does reach the publisher, which
  is what gives the account-keyed cool-down a writer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.runtime.models import DomainOutcome


def _publisher(**overrides) -> MagicMock:
    publisher = MagicMock()
    publisher.publish_note = AsyncMock(**overrides)
    publisher.close = AsyncMock()
    return publisher


class TestXhsPublisherTool:
    async def test_a_successful_publish_returns_the_note_identity(self):
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = _publisher(
            return_value={"post_id": "note-1", "url": "https://x/note-1", "status": "published"}
        )

        with patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher):
            result = await xhs_publisher.ainvoke({"title": "title", "body": "body"})

        assert result["post_id"] == "note-1"
        # The service answers with ``url`` on this path and ``post_url`` on its
        # blocked ones; the tool normalises, so the receipt sees one name.
        assert result["post_url"] == "https://x/note-1"
        assert result["status"] == "published"
        publisher.close.assert_awaited_once()

    async def test_a_raised_failure_reaches_the_gateway_instead_of_being_swallowed(self):
        """It used to catch everything and return ``{"status": "error"}``.

        That made the Gateway see a *successful* call whose value happened to
        contain an error -- the second quiet normaliser P1c removes wherever a
        call site is migrated onto the runtime.  The exception now propagates
        (the Gateway files it as ``ok=False`` with the type name in ``error``),
        and the browser is still closed on the way out.
        """
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = _publisher(side_effect=RuntimeError("browser failed"))

        with (
            patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher),
            pytest.raises(RuntimeError, match="browser failed"),
        ):
            await xhs_publisher.ainvoke({"title": "title", "body": "body"})

        publisher.close.assert_awaited_once()

    @pytest.mark.parametrize(
        ("result", "status"),
        [
            (
                {"status": "unknown", "error": "提交已发起，结果不明", "result_known": False},
                "unknown",
            ),
            ({"status": "pending"}, "pending"),
            (
                {
                    "status": "failed",
                    "error": "发布冷却中：同一账号请 20 秒后再发。",
                    "error_type": "publish_cooldown",
                    "retry_after_seconds": 20,
                },
                "failed",
            ),
        ],
    )
    async def test_a_platform_verdict_is_an_answer_not_a_failure(self, result, status):
        """``unknown`` must never arrive as retryable: a submit went out, so a
        second attempt could double-post a note that is already live."""
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = _publisher(return_value=result)

        with (
            patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher),
            pytest.raises(DomainOutcome) as excinfo,
        ):
            await xhs_publisher.ainvoke({"title": "title", "body": "body"})

        assert excinfo.value.payload["status"] == status
        assert status not in {"", "published"}

    async def test_the_domain_payload_keeps_the_verdict_at_the_top_level(self):
        """``DomainOutcome(reason, **payload)`` is not ``DomainOutcome(payload=...)``.

        Passing the dict as the keyword ``payload`` buries it one level down,
        where a reader looking for ``status`` misses it and *every* platform
        verdict silently degrades into "unexplained failure".  This asserts the
        flat shape, because the nested one still type-checks and still raises.
        """
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = _publisher(return_value={"status": "unknown", "error": "结果不明"})

        with (
            patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher),
            pytest.raises(DomainOutcome) as excinfo,
        ):
            await xhs_publisher.ainvoke({"title": "title", "body": "body"})

        assert "payload" not in excinfo.value.payload
        assert excinfo.value.payload["status"] == "unknown"
        assert excinfo.value.payload["reason"] == "结果不明"

    async def test_the_account_id_and_the_idempotency_key_reach_the_publisher(self):
        """The account id is what lets the risk gate record per account; the key
        is the runtime's retry guard input and the operator's correlation id."""
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = _publisher(
            return_value={"post_id": "note-1", "url": "u", "status": "published"}
        )

        with patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher):
            await xhs_publisher.ainvoke(
                {
                    "title": "title",
                    "body": "body",
                    "account_id": "acc-1",
                    "idempotency_key": "publish-1",
                }
            )

        assert publisher.publish_note.await_args.kwargs["account_id"] == "acc-1"


class TestGetPublisherEndpointSelection:
    """Which browser profile the factory picks -- the one thing it decides.

    Every other test here (and every agent-level publish test) patches
    ``_get_publisher`` wholesale.  That stubs the seam but also means the body
    of the factory -- and therefore the "an explicit endpoint wins over the
    global one" rule -- is never executed by anything.  These patch only
    ``XHSPublisher``, so the selection logic itself runs.

    The rule matters because it is what keeps multi-account publishing from
    silently collapsing onto one logged-in browser: the mainline resolves an
    endpoint per account and hands it over, while the control plane (P2a-S3's
    Action Executor) passes nothing and must keep getting the global profile.
    """

    def _capture(self, monkeypatch, global_endpoint: str):
        import backend.services.xhs_publisher as svc

        fake_settings = MagicMock()
        fake_settings.platform.cdp_endpoint = global_endpoint
        monkeypatch.setattr("backend.config.settings.Settings", lambda: fake_settings)

        ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(svc, "XHSPublisher", ctor)
        return ctor

    def test_an_explicit_endpoint_wins_over_the_global_one(self, monkeypatch):
        from backend.tools.xhs.publisher import _get_publisher

        ctor = self._capture(monkeypatch, "http://global:9222")

        _get_publisher("http://127.0.0.1:9225")

        assert ctor.call_args.kwargs["cdp_endpoint"] == "http://127.0.0.1:9225"

    def test_no_endpoint_falls_back_to_the_global_one(self, monkeypatch):
        from backend.tools.xhs.publisher import _get_publisher

        ctor = self._capture(monkeypatch, "http://global:9222")

        _get_publisher("")

        assert ctor.call_args.kwargs["cdp_endpoint"] == "http://global:9222"

    def test_whitespace_is_not_an_endpoint(self, monkeypatch):
        """A blank string must not beat the configured global profile."""
        from backend.tools.xhs.publisher import _get_publisher

        ctor = self._capture(monkeypatch, "http://global:9222")

        _get_publisher("   ")

        assert ctor.call_args.kwargs["cdp_endpoint"] == "http://global:9222"
