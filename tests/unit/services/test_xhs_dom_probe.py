"""Unit tests for XHS DOM probe — mock page, no network/browser.

Covers probe_publish_page assertion logic: selector hit = pass, miss = fail +
HTML snippet, probe error handled. run_probe graceful-skip path (no env) also
covered without touching a real browser.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from backend.services.xhs_dom_probe import (
    PROBE_SELECTORS,
    ProbeFinding,
    probe_publish_page,
    run_probe,
)


def _mock_locator(count: int) -> MagicMock:
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    return loc


def _mock_page(
    counts: dict[str, int], url: str = "https://creator.xiaohongshu.com/publish/publish"
) -> MagicMock:
    """counts: selector -> count. Unlisted selectors default to 0."""
    page = MagicMock()
    page.url = url
    # tab-switch helpers (probe_publish_page calls these before asserting)
    page.wait_for_selector = AsyncMock()
    page.evaluate = AsyncMock()

    def _locator(selector: str) -> MagicMock:
        # match against the comma-separated selector string in PROBE_SELECTORS
        for _name, sel in PROBE_SELECTORS:
            if sel == selector:
                c = counts.get(_name, 0)
                return _mock_locator(c)
        return _mock_locator(0)

    page.locator = MagicMock(side_effect=_locator)
    page.content = AsyncMock(return_value="<html><body>fake publish page dom</body></html>")
    return page


class TestProbePublishPage:
    async def test_all_selectors_present_all_pass(self):
        counts = {name: 1 for name, _ in PROBE_SELECTORS}
        page = _mock_page(counts)

        report = await probe_publish_page(page)

        assert report.all_passed is True
        assert len(report.findings) == len(PROBE_SELECTORS)
        assert all(f.count == 1 for f in report.findings)

    async def test_missing_selector_marked_fail_with_snippet(self):
        # image_upload_input missing
        counts = {name: 1 for name, _ in PROBE_SELECTORS}
        counts["image_upload_input"] = 0
        page = _mock_page(counts)

        report = await probe_publish_page(page)

        assert report.all_passed is False
        failed = [f for f in report.findings if not f.passed]
        assert len(failed) == 1
        assert failed[0].name == "image_upload_input"
        assert failed[0].html_snippet == "<html><body>fake publish page dom</body></html>"

    async def test_locator_throws_marked_fail_not_crash(self):
        page = MagicMock()
        page.url = "https://creator.xiaohongshu.com/publish/publish"
        page.wait_for_selector = AsyncMock()
        page.evaluate = AsyncMock()

        def _boom(selector: str):
            loc = MagicMock()
            loc.count = AsyncMock(side_effect=RuntimeError("locator broken"))
            return loc

        page.locator = MagicMock(side_effect=_boom)
        page.content = AsyncMock(return_value="<html></html>")

        report = await probe_publish_page(page)

        assert report.all_passed is False
        assert all(not f.passed for f in report.findings)
        # probe error captured in snippet, not raised
        assert "probe error" in report.findings[0].html_snippet

    async def test_url_captured_in_report(self):
        page = _mock_page({name: 1 for name, _ in PROBE_SELECTORS}, url="https://example.com/x")
        report = await probe_publish_page(page)
        assert report.url == "https://example.com/x"


class TestRunProbeGracefulSkip:
    async def test_no_cookie_no_cdp_skips_without_error(self):
        report = await run_probe(cookie="", cdp_endpoint="")
        assert report.all_passed is False
        assert "skip" in report.error.lower()
        assert report.findings == []
        assert report.skipped is True

    async def test_skip_returns_zero_findings(self):
        report = await run_probe(cookie="", cdp_endpoint="")
        # graceful skip must not raise and must not produce spurious findings
        assert report.findings == []


class TestProbeFinding:
    def test_to_dict_roundtrip(self):
        f = ProbeFinding(name="x", selector="sel", passed=True, count=2, html_snippet="")
        d = f.to_dict()
        assert d == {
            "name": "x",
            "selector": "sel",
            "passed": True,
            "count": 2,
            "html_snippet": "",
        }


class TestProbeReportSkipped:
    def test_exception_report_not_skipped(self):
        # A probe exception sets error + empty findings but skipped=False —
        # distinct from graceful skip so CLI exits 1, not 0.
        from backend.services.xhs_dom_probe import ProbeReport

        report = ProbeReport(error="browser crashed", skipped=False)
        assert report.skipped is False
        assert report.all_passed is False

    def test_skip_report_marked_skipped(self):
        from backend.services.xhs_dom_probe import ProbeReport

        report = ProbeReport(error="no env", skipped=True)
        assert report.skipped is True
        assert report.all_passed is False
