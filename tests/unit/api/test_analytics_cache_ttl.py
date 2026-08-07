"""Tests for analytics cache TTL read from AnalyticsSettings."""

from __future__ import annotations

from unittest.mock import patch

from backend.api.routes import analytics


def test_cache_ttl_read_from_settings():
    """_get_cached honors Settings().analytics.cache_ttl, not a hardcoded constant.

    With cache_ttl=0, a freshly-cached entry is already expired
    (time.time() - ts is a tiny non-negative float, and ``< 0`` is False),
    so _get_cached returns None.

    Revert-then-fail: if _get_cached were hardcoded to ``_CACHE_TTL = 30``,
    ``time.time() - ts < 30`` would be True (just set) → returns the value →
    the ``is None`` assertion would FAIL.
    """
    with patch("backend.api.routes.analytics.Settings") as mock_settings:
        # REAL int, not MagicMock — ``float < MagicMock()`` raises TypeError
        # (per #513/#516 trap). 0 = immediate expiry.
        mock_settings.return_value.analytics.cache_ttl = 0

        analytics._cache.clear()
        analytics._set_cached("test_key", {"data": 1})

        # TTL=0 → expired immediately even though we just cached it.
        assert analytics._get_cached("test_key") is None

    # Cleanup: don't leak the cached entry to other tests.
    analytics._cache.clear()
