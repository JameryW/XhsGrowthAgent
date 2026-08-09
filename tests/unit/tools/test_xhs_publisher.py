"""Regression tests for the legacy XHS publisher tool wrapper."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch


class TestXhsPublisherTool:
    async def test_publish_failure_log_includes_exception_type(self, caplog):
        from backend.tools.xhs.publisher import xhs_publisher

        publisher = MagicMock()
        publisher.publish_note = AsyncMock(side_effect=RuntimeError("browser failed"))
        publisher.close = AsyncMock()

        with (
            patch("backend.tools.xhs.publisher._get_publisher", return_value=publisher),
            caplog.at_level(logging.ERROR, logger="xhs_growth.tools.publisher"),
        ):
            result = await xhs_publisher.ainvoke({"title": "title", "body": "body"})

        assert result["status"] == "error"
        assert result["error"] == "browser failed"
        assert any("RuntimeError: browser failed" in record.message for record in caplog.records)
        publisher.close.assert_awaited_once()
