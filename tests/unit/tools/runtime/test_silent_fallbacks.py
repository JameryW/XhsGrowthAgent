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
* ``SERVICE_FALLBACKS`` — the service layer, **empty since 2026-10-19** after
  five instances were removed. Kept as a pinned empty table rather than deleted,
  so a new one has to arrive named and reasoned instead of quietly.

Two shapes are *not* covered and are pinned as such in ``TestKnownBlindSpots``:
a handler that only logs and lets execution fall through to a zero-valued
``return`` *after* the ``try`` (``XHSClient.get_post_analytics``, fixed
2026-10-19), and a handler that silently ``continue``s past the failed item
(``monitor_keywords``, fixed 2026-10-19). Both read as "failure became data" to
a human and are invisible to this scan by construction — only behaviour tests
hold them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.runtime.audit import (
    TOOLS_ROOT,
    SilentFallback,
    scan_ref_fallbacks,
    scan_silent_fallbacks,
)

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

#: The service layer's remaining instances. **Empty, since 2026-10-19.**
#:
#: Five were here and are gone: ``get_trending`` / ``search_posts`` / the three
#: blogger methods (``search_users`` / ``get_user_info`` / ``get_user_notes``).
#: Each answered a raised exception with ``[]`` or ``{}`` — values that are also
#: the correct answer to "there is nothing here". The callers already degraded
#: from ``ToolResult(ok=False)``; the swallow bought only a dishonest trace.
#:
#: "Empty" here is a *statement*, not an omission: the scan is still run and
#: still compared to this table, so a new instance has to arrive with a name and
#: a reason rather than quietly. If one appears, the question is the same as for
#: the tool surface — not "which register" but "why does this handler exist".
SERVICE_FALLBACKS: dict[str, str] = {}

#: The catalogue's ``tool_ref`` functions — what the Gateway actually invokes.
#: **Empty since 2026-10-20**, when the one instance here was removed:
#: ``backend.tools.ripple.integration:get_report`` returned ``{"error": ...}``
#: from its own ``except``, so the Gateway filed a failed report as ``ok=True``
#: and the caller kept a private convention (``if "error" in report``) to learn
#: what the trace had just denied.
#:
#: It had been invisible to both existing registers by construction: it is not
#: decorated ``@tool`` (``scan_silent_fallbacks``) and it does not live in
#: ``xhs_client.py`` (``SERVICE_FALLBACKS``). Most catalogue refs are plain
#: ``async def``s, so "the surface an agent reads" and "the surface the Gateway
#: calls" were never the same set. Kept empty and still measured, for the same
#: reason the other two are.
REF_FALLBACKS: dict[str, str] = {}


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


class TestTheServiceSurface:
    def test_the_service_layer_has_no_silent_fallbacks(self):
        """Pinned *empty* — and the comparison is against the scan, not prose.

        Five were removed on 2026-10-19. The test name says "has none" rather
        than "has exactly these" because an empty table still has to be measured:
        deleting the assertion instead of asserting nothing would leave the
        next instance completely unwatched.
        """
        found = scan_silent_fallbacks(XHS_CLIENT, tool_only=False)
        assert _refs(found) == sorted(SERVICE_FALLBACKS), (
            "A read method in XHSClient gained or lost a literal fallback. The "
            "service register is empty on purpose: every one of these turned a "
            "failed read into an empty result, which is also the answer to "
            "'there is nothing here'.\n"
            f"seen: {[(item.ref, item.returned) for item in found]}"
        )

    def test_every_entry_says_why_it_stays(self):
        assert all(reason.strip() for reason in SERVICE_FALLBACKS.values())


class TestTheRefSurface:
    """The functions the Gateway calls, which neither other register saw."""

    def test_no_catalogue_ref_answers_failure_with_a_literal(self):
        found = scan_ref_fallbacks()
        assert _refs(found) == sorted(REF_FALLBACKS), (
            "A catalogue ref started (or stopped) answering a failure with a "
            "written-down value. These are the functions the Gateway actually "
            "invokes: a literal here is a failed call recorded as ok=True, and "
            "the only caller that can then tell is one that knows the "
            "convention by heart.\n"
            f"seen: {[(item.ref, item.returned) for item in found]}"
        )

    def test_every_entry_says_why_it_stays(self):
        assert all(reason.strip() for reason in REF_FALLBACKS.values())


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

    # ── the catalogue-ref scan ─────────────────────────────────────────────

    def _ref_tree(self, tmp_path: Path, ref: str, body: str) -> Path:
        """A minimal tree: one module, and a catalogue that points at it."""
        module, _, _qualname = ref.partition(":")
        path = tmp_path / Path(module.replace(".", "/")).with_suffix(".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        catalogue = tmp_path / "catalog.py"
        catalogue.write_text(f"tool_ref({ref!r})\n", encoding="utf-8")
        return catalogue

    def test_a_ref_function_swallowing_a_failure_is_found(self, tmp_path: Path):
        """The shape ``get_report`` had, in a tree of its own."""
        ref = "backend.tools.fake.reports:get_report"
        catalogue = self._ref_tree(
            tmp_path,
            ref,
            "async def get_report(job_id: str) -> dict:\n"
            "    try:\n"
            "        return {'rounds': []}\n"
            "    except Exception as e:\n"
            "        return {'error': str(e)}\n",
        )
        found = scan_ref_fallbacks(catalogue_path=catalogue, root=tmp_path)
        assert [item.ref for item in found] == [ref]
        assert found[0].returned == "{'error': str(e)}"

    def test_a_ref_function_that_does_not_swallow_is_not_flagged(self, tmp_path: Path):
        ref = "backend.tools.fake.reports:get_report"
        catalogue = self._ref_tree(
            tmp_path,
            ref,
            "async def get_report(job_id: str) -> dict:\n    return {'rounds': []}\n",
        )
        assert scan_ref_fallbacks(catalogue_path=catalogue, root=tmp_path) == ()

    def test_a_computed_fallback_is_not_a_written_down_value(self, tmp_path: Path):
        """``return fallback`` (``polish_copy``) is an answer, not a constant.

        The register's criterion has always been "a literal, written down at
        authoring time". Handing back a value another function computed is a
        designed degradation — a different question, and one this scan
        deliberately does not answer.
        """
        ref = "backend.tools.fake.polish:polish_copy"
        catalogue = self._ref_tree(
            tmp_path,
            ref,
            "async def polish_copy(text: str) -> dict:\n"
            "    fallback = algorithmic(text)\n"
            "    try:\n"
            "        return await llm(text)\n"
            "    except Exception:\n"
            "        return fallback\n",
        )
        assert scan_ref_fallbacks(catalogue_path=catalogue, root=tmp_path) == ()

    def test_a_ref_with_no_source_is_an_error_not_a_clean_scan(self, tmp_path: Path):
        """ "Nothing to read" must not come back as "nothing to report"."""
        catalogue = tmp_path / "catalog.py"
        catalogue.write_text("tool_ref('backend.tools.fake.gone:get_report')\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            scan_ref_fallbacks(catalogue_path=catalogue, root=tmp_path)

    def test_a_ref_naming_a_function_that_is_gone_is_an_error_too(self, tmp_path: Path):
        ref = "backend.tools.fake.reports:get_report"
        catalogue = self._ref_tree(
            tmp_path,
            ref,
            "async def something_else(job_id: str) -> dict:\n    return {}\n",
        )
        with pytest.raises(LookupError):
            scan_ref_fallbacks(catalogue_path=catalogue, root=tmp_path)


class TestKnownBlindSpots:
    """Shapes this scan cannot see — pinned so "clean" is never read as "all".

    The judge is *a literal returned from an except handler*, and two shapes
    that lie the same way never do that:

    * **fall-through to a zero-valued constructor** — ``get_post_analytics``
      answered a failed fetch (and a missing cookie) with
      ``XHSAnalytics(post_id=...)``, a zero object that reads as "this post has
      0 views". The handler only logged; the ``return`` sat *after* the
      ``try``, so no handler owns it.
    * **silent drop** — ``monitor_keywords`` used to ``continue`` past a failed
      keyword, so a five-word batch that failed on two arrived as three rows
      and read as "only three were monitored".

    Only behaviour tests catch these
    (``test_get_post_analytics_*`` in ``tests/unit/services/test_xhs_client.py``,
    ``test_monitor_keywords_propagates_a_failed_keyword``). This class pins the
    *limit* of the scan on purpose: if the scan ever learns to see either
    shape, these assertions go red and the blind spot must move from
    "invisible" to "counted" in the same commit — the reverse of what happened
    when a fix was believed because a register changed colour while the
    behaviour tests stayed green.
    """

    def _tree(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "backend" / "tools" / "xhs" / "one.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_fall_through_to_a_zero_object_is_invisible_to_the_scan(self, tmp_path: Path):
        """The 2026-10-19 ``get_post_analytics`` shape, reduced.

        Asserting the *miss* is the point: the guard that catches this lives in
        the behaviour tests, and pretending otherwise is how the swallow
        survived a register that already said "empty".
        """
        self._tree(
            tmp_path,
            "def one() -> object:\n"
            "    try:\n"
            "        return 1\n"
            "    except Exception:\n"
            "        pass\n"
            "    return Zero(post_id='x')\n",
        )
        assert scan_silent_fallbacks(tmp_path / "backend" / "tools", tool_only=False) == ()

    def test_a_silent_drop_is_invisible_to_the_scan(self, tmp_path: Path):
        """The ``monitor_keywords`` shape: the failure just goes missing."""
        self._tree(
            tmp_path,
            "def one(items: list) -> list:\n"
            "    out = []\n"
            "    for item in items:\n"
            "        try:\n"
            "            out.append(fetch(item))\n"
            "        except Exception:\n"
            "            continue\n"
            "    return out\n",
        )
        assert scan_silent_fallbacks(tmp_path / "backend" / "tools", tool_only=False) == ()
