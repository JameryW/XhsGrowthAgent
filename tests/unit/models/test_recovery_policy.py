"""Recovery classification — denial stops, bad requests degrade, transients retry."""

from __future__ import annotations

import pytest

from backend.models.recovery_policy import RecoveryAction, classify_recovery


class RateLimitError(Exception):
    status_code = 429


class ServerError(Exception):
    status_code = 503


class ReadTimeoutError(Exception):
    pass


class AuthenticationError(Exception):
    status_code = 401


class PermissionDeniedError(Exception):
    status_code = 403


class BadRequestError(Exception):
    status_code = 400


class UnprocessableError(Exception):
    status_code = 422


class ContentPolicyError(Exception):
    pass


class WeirdError(Exception):
    pass


class TestDenial:
    @pytest.mark.parametrize(
        "exc", [AuthenticationError(), PermissionDeniedError(), ContentPolicyError()]
    )
    def test_denials_stop_even_when_retryable_looking(self, exc):
        assert classify_recovery(exc) is RecoveryAction.STOP_AND_REPORT

    def test_denial_wins_over_transient_name(self):
        class RateLimitPermissionDeniedError(Exception):
            status_code = 403

        assert classify_recovery(RateLimitPermissionDeniedError()) is RecoveryAction.STOP_AND_REPORT


class TestBadArguments:
    @pytest.mark.parametrize(
        "exc", [BadRequestError(), UnprocessableError(), ValueError("bad json schema")]
    )
    def test_bad_arguments_degrade(self, exc):
        # ValueError has no hints — only the 400/422 statuses and named hints
        # degrade; a bare ValueError falls through to the unknown branch.
        if isinstance(exc, ValueError):
            assert classify_recovery(exc) is RecoveryAction.RETRY_SAME
        else:
            assert classify_recovery(exc) is RecoveryAction.DEGRADE_MODEL

    def test_structured_output_error_degrades(self):
        from pydantic import BaseModel

        from backend.models.structured import StructuredOutputError

        class _Payload(BaseModel):
            value: str

        exc = StructuredOutputError(_Payload, [])
        assert classify_recovery(exc) is RecoveryAction.DEGRADE_MODEL


class TestTransient:
    @pytest.mark.parametrize("exc", [RateLimitError(), ServerError(), ReadTimeoutError()])
    def test_transient_retries_same(self, exc):
        assert classify_recovery(exc, attempt=0, max_attempts=3) is RecoveryAction.RETRY_SAME

    def test_transient_past_budget_stops(self):
        assert classify_recovery(RateLimitError(), attempt=3, max_attempts=3) is (
            RecoveryAction.STOP_AND_REPORT
        )


class TestStalled:
    def test_stalled_escalates_when_action_available(self):
        assert classify_recovery(WeirdError(), stalled=True) is RecoveryAction.ESCALATE_MODEL

    def test_stalled_without_action_falls_back_to_retry(self):
        assert (
            classify_recovery(WeirdError(), stalled=True, action_available=False)
            is RecoveryAction.RETRY_SAME
        )

    def test_denial_still_wins_over_stalled(self):
        assert classify_recovery(PermissionDeniedError(), stalled=True) is (
            RecoveryAction.STOP_AND_REPORT
        )


class TestUnknown:
    def test_unknown_retries_until_budget(self):
        assert classify_recovery(WeirdError(), attempt=0, max_attempts=3) is (
            RecoveryAction.RETRY_SAME
        )
        assert classify_recovery(WeirdError(), attempt=3, max_attempts=3) is (
            RecoveryAction.STOP_AND_REPORT
        )


class TestRetryLayerConsistency:
    """The two rule tables must agree: retryable here == RETRY_SAME there."""

    @pytest.mark.parametrize(
        "exc",
        [
            RateLimitError(),
            ServerError(),
            ReadTimeoutError(),
            BadRequestError(),
            AuthenticationError(),
        ],
    )
    def test_retryable_implies_retry_same(self, exc):
        from backend.models.retry import _is_retryable

        action = classify_recovery(exc, attempt=0, max_attempts=3)
        if _is_retryable(exc):
            assert action is RecoveryAction.RETRY_SAME
        else:
            assert action is not RecoveryAction.RETRY_SAME
