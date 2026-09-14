"""D2' contract tests: ``require_niche`` fail-fast helper.

The legacy ``state.get("niche", "母婴")`` silently compiled an invented
niche into every agent prompt. P1b-S4-7 replaces it with an explicit
fail-fast: workflow start must resolve the niche; agents must never
invent a default.
"""

import pytest

from backend.context.models import require_niche


class TestRequireNiche:
    def test_returns_existing_niche(self):
        assert require_niche({"niche": "母婴"}) == "母婴"

    def test_returns_niche_without_defaults(self):
        assert require_niche({"niche": "美妆", "other": 1}) == "美妆"

    @pytest.mark.parametrize(
        "state",
        [
            {},
            {"niche": None},
            {"niche": ""},
            {"niche": "   "},
        ],
        ids=["missing", "none", "empty", "whitespace"],
    )
    def test_missing_niche_raises(self, state):
        with pytest.raises(ValueError, match="D2'"):
            require_niche(state)

    def test_error_message_is_actionable(self):
        with pytest.raises(ValueError) as exc_info:
            require_niche({})
        msg = str(exc_info.value)
        assert "niche is required" in msg
        assert "workflow start" in msg
