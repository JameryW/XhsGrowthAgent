"""Progress Detector signals — stall detection must be evidence-based."""

from __future__ import annotations

from backend.state.progress import (
    PROGRESS_EVENT_KIND,
    ProgressSignal,
    detect_progress,
    progress_event,
)


def _llm(error: str = "", **extra):
    entry = {"kind": "llm", "model": "m"}
    if error:
        entry["error"] = error
    entry.update(extra)
    return entry


def _tool(result, **extra):
    entry = {"kind": "tool", "tool": "t", "result": result}
    entry.update(extra)
    return entry


class TestNoSignal:
    def test_empty_timeline_is_not_a_stall(self):
        signal = detect_progress([])
        assert signal.stalled is False
        assert signal.reason == ""

    def test_short_timeline_is_not_a_stall(self):
        assert detect_progress([_llm("boom"), _llm("boom")]).stalled is False

    def test_distinct_errors_are_progress(self):
        events = [_llm("schema error"), _llm("timeout"), _llm("empty response")]
        assert detect_progress(events).stalled is False

    def test_single_occurrence_never_stalls(self):
        # window=1 would turn every failure into a stall; it is clamped to 2.
        assert detect_progress([_llm("boom")], window=1).stalled is False
        assert detect_progress([_llm("boom"), _llm("boom")], window=1).stalled is True


class TestSameErrorRepeated:
    def test_three_identical_errors_stall(self):
        signal = detect_progress(
            [_llm("400 invalid schema"), _llm("400 invalid schema"), _llm("400 invalid schema")]
        )
        assert signal.stalled is True
        assert signal.reason == "same_error_repeated"
        assert signal.evidence["count"] == 3
        assert signal.evidence["fingerprint"]

    def test_structured_error_fingerprints_by_content(self):
        a = {"kind": "tool", "error": {"type": "timeout", "message": "read timed out"}}
        b = {
            "mesage": "x",
            "error": {"message": "read timed out", "type": "timeout"},
            "kind": "tool",
        }
        signal = detect_progress([a, b, a])
        assert signal.stalled is True
        # Same content in a different key order must fingerprint identically.
        assert signal.evidence["count"] == 3

    def test_non_consecutive_errors_do_not_stall(self):
        events = [_llm("boom"), _llm(""), _llm("boom"), _llm("boom")]
        # Only the trailing two carry errors — below the default window.
        assert detect_progress(events).stalled is False

    def test_error_type_field_is_used_when_error_absent(self):
        events = [
            {"kind": "tool", "error_type": "publish_result_unknown", "message": "no verdict"},
            {"kind": "tool", "error_type": "publish_result_unknown", "message": "no verdict"},
            {"kind": "tool", "error_type": "publish_result_unknown", "message": "no verdict"},
        ]
        signal = detect_progress(events)
        assert signal.stalled is True
        assert signal.reason == "same_error_repeated"


class TestToolOutputRepeated:
    def test_identical_payloads_stall(self):
        events = [_tool({"rows": 0}), _tool({"rows": 0}), _tool({"rows": 0})]
        signal = detect_progress(events)
        assert signal.stalled is True
        assert signal.reason == "tool_output_repeated"
        assert signal.evidence["digest"]

    def test_key_order_does_not_matter(self):
        events = [_tool({"a": 1, "b": 2}), _tool({"b": 2, "a": 1}), _tool({"a": 1, "b": 2})]
        assert detect_progress(events).stalled is True

    def test_changing_payloads_are_progress(self):
        events = [_tool({"rows": 0}), _tool({"rows": 1}), _tool({"rows": 2})]
        assert detect_progress(events).stalled is False

    def test_error_stall_wins_over_output_stall(self):
        events = [
            _tool({"ok": False}, error="rate limited"),
            _tool({"ok": False}, error="rate limited"),
            _tool({"ok": False}, error="rate limited"),
        ]
        signal = detect_progress(events)
        assert signal.reason == "same_error_repeated"


class TestEventRendering:
    def test_not_stalled_renders_nothing(self):
        assert ProgressSignal(stalled=False).to_event() is None

    def test_stalled_signal_renders_progress_event(self):
        signal = detect_progress([_llm("boom")] * 3)
        entry = progress_event(signal, account_id="acct", thread_id="th")
        assert entry["kind"] == PROGRESS_EVENT_KIND
        assert entry["reason"] == "same_error_repeated"
        assert entry["account_id"] == "acct"
        assert entry["thread_id"] == "th"
        assert entry["window"] == 3
        assert entry["timestamp"]

    def test_signal_to_event_delegates(self):
        signal = detect_progress([_tool({"x": 1})] * 3)
        entry = signal.to_event(account_id="a")
        assert entry is not None and entry["kind"] == PROGRESS_EVENT_KIND

    def test_event_kind_is_registered(self):
        # Same pinning discipline as action/verification: an emitter whose kind
        # is not declared in EVENT_KINDS drifts away from every reader that
        # enumerates the timeline vocabulary.
        from backend.db.workflow_events import EVENT_KINDS

        assert PROGRESS_EVENT_KIND in EVENT_KINDS
