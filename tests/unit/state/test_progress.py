"""Progress Detector signals — stall detection must be evidence-based."""

from __future__ import annotations

from backend.state.progress import (
    PROGRESS_EVENT_KIND,
    REVISION_NO_IMPROVEMENT,
    REVISION_SAME_HINTS,
    ProgressSignal,
    detect_progress,
    detect_revision_stall,
    progress_event,
    revision_record,
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


def _verdict(
    round_no: int,
    *,
    score: float | None = 60.0,
    hints: list[str] | None = None,
    decision: object = "needs_revision",
    degraded: bool = False,
) -> dict:
    evaluation = {
        "overall_score": score,
        "revision_hints": list(hints or []),
        "decision": decision,
    }
    if degraded:
        evaluation["degraded"] = True
        evaluation["status"] = "degraded"
    record = revision_record(round_no, evaluation)
    assert record is not None
    return record


class TestRevisionRecord:
    """The record is the input the score/hint rules need — keep it minimal."""

    def test_no_verdict_records_nothing(self):
        # A neutral filler would look like "no change" and manufacture stalls.
        assert revision_record(1, None) is None
        assert revision_record(1, {}) is None

    def test_hint_text_stays_out_of_the_record(self):
        record = _verdict(1, hints=["标题缺具体收益", "正文第二段太虚"])
        assert record["hints_digest"]
        assert "revision_hints" not in record
        assert "标题缺具体收益" not in str(record)

    def test_digest_ignores_hint_order(self):
        one = _verdict(1, hints=["a", "b"])
        two = _verdict(2, hints=["b", "a"])
        assert one["hints_digest"] == two["hints_digest"]

    def test_enum_decision_is_stored_by_value(self):
        from backend.state.enums import ContentStatus

        record = _verdict(1, decision=ContentStatus.NEEDS_REVISION)
        assert record["decision"] == ContentStatus.NEEDS_REVISION.value

    def test_degraded_verdict_keeps_no_score(self):
        record = _verdict(1, score=None, degraded=True)
        assert record["score"] is None
        assert record["degraded"] is True


class TestRevisionStall:
    """Round-level stall detection over the evaluator→copywriter loop."""

    def test_single_round_is_not_a_stall(self):
        assert detect_revision_stall([_verdict(1)]).stalled is False

    def test_same_hints_twice_stall(self):
        rounds = [
            _verdict(1, score=60.0, hints=["标题缺具体收益"]),
            _verdict(2, score=61.0, hints=["标题缺具体收益"]),
        ]
        signal = detect_revision_stall(rounds)
        assert signal.stalled is True
        assert signal.reason == REVISION_SAME_HINTS
        assert signal.evidence["rounds"] == [1, 2]
        assert signal.evidence["count"] == 2

    def test_different_hints_without_score_movement_stall(self):
        rounds = [
            _verdict(1, score=60.4, hints=["标题缺具体收益"]),
            _verdict(2, score=60.9, hints=["正文第二段太虚"]),
        ]
        signal = detect_revision_stall(rounds)
        assert signal.stalled is True
        assert signal.reason == REVISION_NO_IMPROVEMENT
        # 0.5 points on a 0-100 panel is a wobble, not progress.
        assert signal.evidence["gain"] == 0.5
        assert signal.evidence["min_gain"] == 1.0

    def test_real_improvement_is_progress(self):
        rounds = [
            _verdict(1, score=60.0, hints=["标题缺具体收益"]),
            _verdict(2, score=66.0, hints=["正文第二段太虚"]),
        ]
        assert detect_revision_stall(rounds).stalled is False

    def test_exactly_one_point_is_enough(self):
        rounds = [
            _verdict(1, score=60.0, hints=["a"]),
            _verdict(2, score=61.0, hints=["b"]),
        ]
        assert detect_revision_stall(rounds).stalled is False

    def test_degraded_scores_carry_no_evidence(self):
        # A degraded panel judged nothing; reading None as "no improvement"
        # would report a stall for a loop nobody measured.
        rounds = [
            _verdict(1, score=None, hints=["a"], degraded=True),
            _verdict(2, score=None, hints=["b"], degraded=True),
        ]
        assert detect_revision_stall(rounds).stalled is False

    def test_missing_hints_do_not_count_as_repetition(self):
        rounds = [_verdict(1, score=50.0), _verdict(2, score=50.0)]
        signal = detect_revision_stall(rounds)
        # No hints at all is not "the same hints"; the score rule still holds.
        assert signal.reason == REVISION_NO_IMPROVEMENT

    def test_human_reset_starts_a_new_epoch(self):
        # The human "revise" resume resets revision_count to 0, so round
        # numbers restart. Comparing across the reset would report a stall for
        # a loop the operator deliberately restarted with a fresh budget.
        rounds = [
            _verdict(1, score=60.0, hints=["标题缺具体收益"]),
            _verdict(2, score=60.0, hints=["标题缺具体收益"]),
            _verdict(1, score=60.0, hints=["标题缺具体收益"]),
        ]
        assert detect_revision_stall(rounds).stalled is False

    def test_epoch_boundary_is_the_round_gap_not_the_count(self):
        rounds = [
            _verdict(1, score=60.0, hints=["a"]),
            _verdict(3, score=60.0, hints=["a"]),
        ]
        # A gap means the rounds are not consecutive: no window to compare.
        assert detect_revision_stall(rounds).stalled is False

    def test_window_is_clamped_to_two(self):
        rounds = [
            _verdict(1, score=60.0, hints=["a"]),
            _verdict(2, score=60.0, hints=["a"]),
        ]
        signal = detect_revision_stall(rounds, window=1)
        assert signal.stalled is True
        assert signal.window == 2
