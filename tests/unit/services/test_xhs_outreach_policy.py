"""The per-account outreach policy (§9.5) — source, precedence, fail-safe.

Four things are pinned here.

1. **Where the policy comes from.**  The account's own rows first (and *final*:
   a row that carries a policy key is never overridden by the deployment
   default — falling through would let the deployment silently widen an
   account an operator narrowed); the deployment environment second; the safe
   default third.  The legacy ``XHS_ALLOW_OUTBOUND_DM`` switch survives as the
   deployment's opt-in, because it predates this model and its users meant
   something by it.
2. **Fail-safe in one direction only.**  An unreadable store, a malformed
   value, or an unknown mode name land on *more* restriction, never less —
   the policy counterpart of the credential resolver's "unknown is not
   permission to act as somebody else".
3. **The three questions are predicates, not folklore.**  ``reply_only`` /
   ``allows_engagement`` / ``allows_proactive`` are derived, so "是否只允许
   应答式触达" cannot drift from "谁被允许触达".
4. **The default reader is the production read.**  Asserted against the real
   ``CredentialRow`` type and its real ``value`` property, the same way
   ``test_xhs_credentials`` pins its half of the same table.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from backend.db.accounts import CredentialRow
from backend.services.xhs_outreach_policy import (
    DAILY_PROACTIVE_CAP_KEY,
    MODE_KEY,
    OUTREACH_CONFIRMED,
    OUTREACH_INBOUND,
    OUTREACH_NOBODY,
    XhsOutreachPolicy,
    load_outreach_policy,
    policy_from_values,
)

_ENV_KEYS = (MODE_KEY, DAILY_PROACTIVE_CAP_KEY, "XHS_ALLOW_OUTBOUND_DM")


@pytest.fixture(autouse=True)
def _clean_deployment(monkeypatch):
    """The deployment env is an input, not ambient state."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def _reader(**rows: str):
    async def _read(account_id: str) -> Mapping[str, str]:
        return dict(rows)

    return _read


def _reader_that_raises():
    async def _read(account_id: str) -> Mapping[str, str]:
        raise RuntimeError("accounts table unreachable")

    return _read


class TestTheSafeDefault:
    async def test_nothing_configured_answers_inbound_only(self):
        policy = await load_outreach_policy("acc-1", reader=_reader())

        assert policy == XhsOutreachPolicy(
            account_id="acc-1", mode=OUTREACH_INBOUND, daily_proactive_cap=0
        )
        assert policy.reply_only is True
        assert policy.allows_engagement is True  # replies are not outreach
        assert policy.allows_proactive is False

    async def test_a_blank_account_gets_the_same_safe_default(self):
        policy = await load_outreach_policy("", reader=_reader())

        assert policy.mode == OUTREACH_INBOUND
        assert policy.allows_proactive is False


class TestWhereThePolicyComesFrom:
    async def test_the_accounts_own_row_wins(self, monkeypatch):
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")  # deployment says yes
        policy = await load_outreach_policy(
            "acc-1",
            reader=_reader(**{MODE_KEY: OUTREACH_NOBODY, DAILY_PROACTIVE_CAP_KEY: "0"}),
        )

        assert policy.mode == OUTREACH_NOBODY

    async def test_a_narrowing_account_row_is_not_widened_by_the_deployment(self):
        """The direction that must never invert.

        A row that says ``inbound_only`` is an operator narrowing the account;
        consulting the deployment default over it would open cold outreach the
        account was explicitly denied.
        """
        policy = await load_outreach_policy(
            "acc-1",
            reader=_reader(**{MODE_KEY: OUTREACH_INBOUND}),
        )

        assert policy.mode == OUTREACH_INBOUND
        assert policy.allows_proactive is False

    async def test_rows_silent_on_policy_fall_through_to_the_deployment(self, monkeypatch):
        """A cookie row is not a policy statement.

        ``account_credentials`` is a per-account key-value table shared with
        the credential resolver; rows that carry only credential keys say
        nothing about outreach.
        """
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        policy = await load_outreach_policy(
            "acc-1",
            reader=_reader(**{"XHS_COOKIE": "a1=" + "0" * 20}),
        )

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 20  # the legacy bound

    async def test_the_deployment_cap_env_overrides_the_legacy_default(self, monkeypatch):
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        monkeypatch.setenv(DAILY_PROACTIVE_CAP_KEY, "3")
        policy = await load_outreach_policy("acc-1", reader=_reader())

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 3

    async def test_the_mode_env_beats_the_legacy_switch(self, monkeypatch):
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        monkeypatch.setenv(MODE_KEY, OUTREACH_NOBODY)
        policy = await load_outreach_policy("acc-1", reader=_reader())

        assert policy.mode == OUTREACH_NOBODY

    async def test_the_legacy_switch_alone_opens_confirmed_outreach(self, monkeypatch):
        """Existing opt-ins keep meaning what they meant (2026-10 migration)."""
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        policy = await load_outreach_policy("acc-1", reader=_reader())

        assert policy.allows_proactive is True


class TestFailSafeAtEveryEdge:
    async def test_a_raising_reader_yields_the_safe_default(self, monkeypatch):
        """Unknown is not permission — and not the deployment's permission either."""
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
        policy = await load_outreach_policy("acc-1", reader=_reader_that_raises())

        assert policy.mode == OUTREACH_INBOUND
        assert policy.allows_proactive is False

    def test_an_unknown_mode_name_is_not_a_wider_mode(self):
        policy = policy_from_values("acc-1", {MODE_KEY: "everyone"})

        assert policy.mode == OUTREACH_INBOUND

    def test_a_malformed_cap_is_zero_not_unlimited(self):
        policy = policy_from_values(
            "acc-1",
            {MODE_KEY: OUTREACH_CONFIRMED, DAILY_PROACTIVE_CAP_KEY: "many"},
        )

        assert policy.daily_proactive_cap == 0
        assert policy.allows_proactive is False  # 0 of something is none of it

    def test_a_negative_cap_is_clamped_to_zero(self):
        policy = policy_from_values("acc-1", {DAILY_PROACTIVE_CAP_KEY: "-5"})

        assert policy.daily_proactive_cap == 0

    def test_a_partial_row_only_fallbacks_the_missing_field(self):
        policy = policy_from_values(
            "acc-1",
            {MODE_KEY: OUTREACH_CONFIRMED},
            fallback=XhsOutreachPolicy(mode=OUTREACH_INBOUND, daily_proactive_cap=7),
        )

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 7


class TestTheThreeQuestionsArePredicates:
    @pytest.mark.parametrize(
        ("mode", "cap", "engagement", "proactive"),
        [
            (OUTREACH_NOBODY, 5, False, False),
            (OUTREACH_INBOUND, 5, True, False),
            (OUTREACH_CONFIRMED, 5, True, True),
            (OUTREACH_CONFIRMED, 0, True, False),
        ],
    )
    def test_mode_and_cap_answer_who_and_how_much(self, mode, cap, engagement, proactive):
        policy = XhsOutreachPolicy(mode=mode, daily_proactive_cap=cap)

        assert policy.allows_engagement is engagement
        assert policy.allows_proactive is proactive
        assert policy.reply_only is (mode == OUTREACH_INBOUND)


class TestTheDefaultReaderIsTheRealPath:
    @staticmethod
    def _store(monkeypatch, rows: list[CredentialRow], decoded: Mapping[bytes, str]) -> None:
        """Serve the rows from the real store read, with real decryption replaced.

        Only ``decrypt_value`` is doubled — the rows are the real ``CredentialRow``
        type and ``row.value`` still runs its own property, the same split
        ``test_xhs_credentials`` uses for the other half of this table.
        """
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

        async def _list(account_id: str) -> list[CredentialRow]:
            assert account_id == "acc-1"
            return rows

        monkeypatch.setattr("backend.db.accounts.list_credentials", _list)
        monkeypatch.setattr("backend.db.accounts.decrypt_value", lambda data: decoded[data])

    async def test_only_policy_keys_survive_the_read(self, monkeypatch):
        rows = [
            CredentialRow(account_id="acc-1", key_name=MODE_KEY, _encrypted_bytes=b"mode"),
            CredentialRow(
                account_id="acc-1", key_name=DAILY_PROACTIVE_CAP_KEY, _encrypted_bytes=b"cap"
            ),
            CredentialRow(account_id="acc-1", key_name="XHS_COOKIE", _encrypted_bytes=b"cookie"),
        ]
        self._store(
            monkeypatch,
            rows,
            {b"mode": OUTREACH_CONFIRMED, b"cap": "4", b"cookie": "x"},
        )

        policy = await load_outreach_policy("acc-1")

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 4

    async def test_no_pool_is_a_configuration_fact_not_a_failure(self, monkeypatch):
        """No account store ⇒ deployment default, never an exception."""
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")

        policy = await load_outreach_policy("acc-1")

        assert policy.mode == OUTREACH_CONFIRMED
