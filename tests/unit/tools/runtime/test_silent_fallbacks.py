"""A failure must not be reported as a value nobody computed.

The shape this file is about:

```python
except Exception:
    return []          # "the platform had nothing"
    return 50          # "heat is 50"
    return {}          # "no data for this user"
```

The handler is reached *because* the call failed, so whatever it hands back
cannot be an answer to the question asked. It is transcription: a value written
down at authoring time, delivered later as if it had been measured.

Three of these were removed on 2026-10-19, each caught in a different layer:

* ``analysis.topic_scorer`` returned ``heat_score=50`` (a constant nobody
  calibrated) and the strategist wrote it into a prompt as platform data;
* ``engagement.fetch_pending_comments`` returned ``[]`` from a client that
  could not read at all, so a human moderation queue always said "nothing left
  to review" — the strongest form of the defect, since it could not succeed;
* ``XHSClient.get_comments`` returned ``[]`` from its own handler, which is why
  fixing only the tool would have been cosmetic.

This file makes the surface countable. Two registers, both compared against a
scan of the sources rather than against a second register:

* ``SILENT_FALLBACKS`` — ``@tool`` functions (the surface an agent reads);
* ``SERVICE_FALLBACKS`` — the service layer's remaining instances, which are
  a named debt: a tool above them may enforce its own precondition, but the
  shape is still there and an uncounted one is the one that comes back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.runtime.audit import TOOLS_ROOT, SilentFallback, scan_silent_fallbacks

SERVICES = TOOLS_ROOT.parent / "services"
XHS_CLIENT = SERVICES / "xhs_client.py"

#: ``@tool`` functions allowed to answer a failure with a literal, and why.
#: An entry with a thin reason is worse than no entry: it reads as settled.
SILENT_FALLBACKS: dict[str, str] = {
    "backend.tools.ripple.client:ripple_cancel_simulation": (
        "The literal *names* the failure: ``{'cancelled': False, 'status': 'error', "
        "'error': str(e)}``. A caller cannot mistake it for success, which is the "
        "whole test. It stays because the tool is ungated — there is no Gateway to "
        "normalise an exception into a ToolResult — so raising would leave the "
        "caller with nothing but a traceback. If this capability ever moves into "
        "the catalogue, the literal must become an exception."
    ),
}

#: The service layer's remaining instances. Debt, counted on purpose.
SERVICE_FALLBACKS: dict[str, str] = {
    "backend.services.xhs_client:XHSClient.get_trending": (
        "Caller is the xhs_trending tool, which now enforces ``require_readable`` "
        "before the call, so the missing-cookie half is closed. The failure half "
        "is not: an HTTP error still arrives as rows of empty data."
    ),
    "backend.services.xhs_client:XHSClient.search_posts": (
        "Four callers with different degradation needs (visual_analysis, "
        "topic_scorer, keyword_monitor, competitor_analyzer). Raising here is a "
        "per-caller decision, so it needs its own slice rather than a blanket swap."
    ),
    "backend.services.xhs_client:XHSClient.search_users": (
        "Not a dead path and not unverifiable — this file first said so and was "
        "wrong. The blogger-reference feature (2026-06) pinned it in "
        "``tests/unit/services/test_xhs_client_blogger.py``, and one of those tests, "
        "``test_search_users_error_returns_empty``, *asserts* the fallback: the "
        "'failure reads as empty' behaviour is a written-down contract there. What "
        "blocks a change is that contract, not a lack of verification. It has no "
        "production caller yet, so changing it means rewriting that test on purpose."
    ),
    "backend.services.xhs_client:XHSClient.get_user_info": (
        "Same feature, same pinned contract (``test_get_user_info_error_returns_empty``)"
        ". Returns ``{}`` — the ambiguity in a mapping rather than a list. Same "
        "question as the other two, one decision covers all three."
    ),
    "backend.services.xhs_client:XHSClient.get_user_notes": (
        "Same feature, same pinned contract (``test_get_user_notes_error_returns_empty``)"
        ". Auto-paginates, so a mid-pagination failure would surface as a short "
        "result set rather than an error — the same lie with a longer fuse."
    ),
}


def _refs(found: tuple[SilentFallback, ...]) -> list[str]:
    return [item.ref for item in found]


class TestTheToolSurface:
    def test_only_the_declared_tools_answer_failure_with_a_literal(self):
        found = scan_silent_fallbacks()
        assert _refs(found) == sorted(SILENT_FALLBACKS), (
            "A @tool either started answering a failure with a literal, or stopped. "
            "If you removed one, drop the entry. If you added one, the question is "
            "not 'which register' but 'why does this handler exist' — a failure the "
            "caller should see is an exception.\n"
            f"seen: {[(item.ref, item.returned) for item in found]}"
        )

    def test_every_entry_says_what_the_literal_means(self):
        assert all(reason.strip() for reason in SILENT_FALLBACKS.values())


class TestTheServiceDebt:
    def test_the_remaining_instances_are_counted(self):
        found = scan_silent_fallbacks(XHS_CLIENT, tool_only=False)
        assert _refs(found) == sorted(SERVICE_FALLBACKS), (
            "A read method in XHSClient gained or lost a literal fallback. This "
            "register is the honest count of where a failed read still arrives as "
            "an empty result.\n"
            f"seen: {[(item.ref, item.returned) for item in found]}"
        )

    def test_every_entry_says_who_is_behind_it(self):
        assert all(reason.strip() for reason in SERVICE_FALLBACKS.values())


class TestPositiveControls:
    """The scan must catch what it claims to catch — from source, not by name."""

    def _tree(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "backend" / "tools" / "xhs" / "one.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_swallowed_failure_returning_empty_is_found(self, tmp_path: Path):
        self._tree(
            tmp_path,
            "from langchain_core.tools import tool\n"
            "\n"
            "\n"
            "@tool\n"
            "def one() -> list:\n"
            "    try:\n"
            "        return [1]\n"
            "    except Exception:\n"
            "        return []\n",
        )
        found = scan_silent_fallbacks(tmp_path / "backend" / "tools")
        assert [item.ref for item in found] == ["backend.tools.xhs.one:one"]
        assert found[0].returned == "[]"

    def test_a_written_down_score_is_found_too(self, tmp_path: Path):
        """The bug that started this: a dict of plausible numbers."""
        self._tree(
            tmp_path,
            "from langchain_core.tools import tool\n"
            "\n"
            "\n"
            "@tool\n"
            "def one() -> dict:\n"
            "    try:\n"
            "        return {}\n"
            "    except Exception:\n"
            "        return {'heat_score': 50, 'recommendation': 'manual'}\n",
        )
        assert [
            item.returned for item in scan_silent_fallbacks(tmp_path / "backend" / "tools")
        ] == ["{'heat_score': 50, 'recommendation': 'manual'}"]

    def test_re_raising_is_not_flagged(self, tmp_path: Path):
        self._tree(
            tmp_path,
            "from langchain_core.tools import tool\n"
            "\n"
            "\n"
            "@tool\n"
            "def one() -> list:\n"
            "    try:\n"
            "        return [1]\n"
            "    except Exception:\n"
            "        raise\n",
        )
        assert scan_silent_fallbacks(tmp_path / "backend" / "tools") == ()

    def test_a_plain_function_is_not_a_tool(self, tmp_path: Path):
        self._tree(
            tmp_path,
            "def one() -> list:\n"
            "    try:\n"
            "        return [1]\n"
            "    except Exception:\n"
            "        return []\n",
        )
        assert scan_silent_fallbacks(tmp_path / "backend" / "tools") == ()
        # ... but the same source scanned as a plain function is exactly what
        # the service-layer register counts.
        assert len(scan_silent_fallbacks(tmp_path / "backend" / "tools", tool_only=False)) == 1

    def test_a_literal_in_a_nested_function_is_not_attributed_to_the_handler(self, tmp_path: Path):
        """``return []`` inside a helper defined by the handler is the helper's."""
        self._tree(
            tmp_path,
            "from langchain_core.tools import tool\n"
            "\n"
            "\n"
            "@tool\n"
            "def one() -> list:\n"
            "    try:\n"
            "        return [1]\n"
            "    except Exception:\n"
            "\n"
            "        def _fallback() -> list:\n"
            "            return []\n"
            "\n"
            "        raise RuntimeError(_fallback())\n",
        )
        assert scan_silent_fallbacks(tmp_path / "backend" / "tools") == ()

    def test_a_file_path_is_scanned_rather_than_silently_empty(self, tmp_path: Path):
        """``Path('x.py').rglob('*.py')`` yields nothing — a false pass.

        Handing the scan a single file is the natural way to ask "what is left
        in this module", and answering it with "clean" because no directory was
        walked is precisely the failure mode this module exists to prevent.
        """
        path = self._tree(
            tmp_path,
            "from langchain_core.tools import tool\n"
            "\n"
            "\n"
            "@tool\n"
            "def one() -> list:\n"
            "    try:\n"
            "        return [1]\n"
            "    except Exception:\n"
            "        return []\n",
        )
        assert len(scan_silent_fallbacks(path)) == 1

    def test_a_missing_root_is_an_error_not_a_clean_result(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            scan_silent_fallbacks(tmp_path / "nope")
