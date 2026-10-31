"""The outreach policy's management write path (票 5ax).

Until this slice the two policy keys could only be written by hand into
``account_credentials``.  These pin the properties the write path must have:

1. **Validated**: only the three declared mode names, only a non-negative int
   cap; a body that names nothing is refused (a management write that writes
   nothing is a caller mistake, not a successful no-op).
2. **Explicit about persistence**: the returned :class:`XhsOutreachPolicy` is
   read back from the store, so the caller sees what the gates will see.
3. **Loud on an unavailable store**: reads may fall back (unknown is not
   permission), writes must not — a silently ignored suspension is worse than
   an error.
4. **Clear really clears**: both rows are deleted, so the deployment default
   applies again (an empty value would still be an account-level statement).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.xhs_outreach_policy import (
    DAILY_PROACTIVE_CAP_KEY,
    MODE_KEY,
    OUTREACH_CONFIRMED,
    OUTREACH_INBOUND,
    OUTREACH_NOBODY,
    OutreachPolicyStoreUnavailableError,
    clear_outreach_policy,
    load_outreach_policy,
    read_outreach_overrides,
    set_outreach_policy,
)

_ENV_KEYS = (MODE_KEY, DAILY_PROACTIVE_CAP_KEY, "XHS_ALLOW_OUTBOUND_DM")


@pytest.fixture(autouse=True)
def _clean_deployment(monkeypatch: pytest.MonkeyPatch):
    """The deployment env is an input, not ambient state."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """An in-memory ``account_credentials`` behind the real reader/writer seams."""
    rows: dict[tuple[str, str], str] = {}

    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    async def _list(account_id: str) -> list[Any]:
        return [
            SimpleNamespace(key_name=key, value=value)
            for (account, key), value in rows.items()
            if account == account_id
        ]

    async def _upsert(account_id: str, key_name: str, value: str) -> None:
        rows[(account_id, key_name)] = value

    async def _delete(account_id: str, key_name: str) -> bool:
        return rows.pop((account_id, key_name), None) is not None

    monkeypatch.setattr("backend.db.accounts.list_credentials", _list)
    monkeypatch.setattr("backend.db.accounts.upsert_credential", _upsert)
    monkeypatch.setattr("backend.db.accounts.delete_credential", _delete)
    return rows


class TestSetWritesAndReadsBack:
    async def test_mode_only_writes_only_that_row(self, store):
        policy = await set_outreach_policy("acc-1", mode=OUTREACH_CONFIRMED)

        assert policy.account_id == "acc-1"
        assert policy.mode == OUTREACH_CONFIRMED
        assert store == {("acc-1", MODE_KEY): OUTREACH_CONFIRMED}

    async def test_cap_only_writes_only_that_row(self, store):
        policy = await set_outreach_policy("acc-1", daily_proactive_cap=5)

        assert policy.mode == OUTREACH_INBOUND  # the safe default, not touched
        assert policy.daily_proactive_cap == 5
        assert store == {("acc-1", DAILY_PROACTIVE_CAP_KEY): "5"}

    async def test_both_fields_are_written_and_resolved(self, store):
        policy = await set_outreach_policy("acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=3)

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 3
        assert await load_outreach_policy("acc-1") == policy

    async def test_an_account_row_is_final_over_the_deployment(self, store, monkeypatch):
        """The precedence rule the reader already had — the writer must feed it."""
        monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")

        policy = await set_outreach_policy("acc-1", mode=OUTREACH_NOBODY)

        assert policy.mode == OUTREACH_NOBODY
        assert policy.allows_engagement is False

    async def test_a_partial_write_keeps_the_existing_other_field(self, store):
        await set_outreach_policy("acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=4)
        policy = await set_outreach_policy("acc-1", daily_proactive_cap=9)

        assert policy.mode == OUTREACH_CONFIRMED
        assert policy.daily_proactive_cap == 9


class TestValidationRefusesBadWrites:
    @pytest.mark.parametrize("mode", ["everyone", "", "  ", "PROACTIVE"])
    async def test_an_unknown_mode_is_refused(self, store, mode):
        with pytest.raises(ValueError, match="unknown outreach mode"):
            await set_outreach_policy("acc-1", mode=mode)
        assert store == {}

    @pytest.mark.parametrize("cap", [-1, "5", 1.5, True])
    async def test_a_non_non_negative_int_cap_is_refused(self, store, cap):
        with pytest.raises(ValueError, match="daily_proactive_cap"):
            await set_outreach_policy("acc-1", daily_proactive_cap=cap)  # type: ignore[arg-type]
        assert store == {}

    async def test_a_write_that_names_no_field_is_refused(self, store):
        with pytest.raises(ValueError, match="at least one"):
            await set_outreach_policy("acc-1")

    async def test_a_blank_account_is_refused(self, store):
        with pytest.raises(ValueError, match="account_id"):
            await set_outreach_policy("   ", mode=OUTREACH_CONFIRMED)


class TestTheStoreMustBeAvailable:
    async def test_set_fails_loudly_without_a_pool(self, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        with pytest.raises(OutreachPolicyStoreUnavailableError, match="account store"):
            await set_outreach_policy("acc-1", mode=OUTREACH_CONFIRMED)

    async def test_clear_fails_loudly_without_a_pool(self, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        with pytest.raises(OutreachPolicyStoreUnavailableError, match="account store"):
            await clear_outreach_policy("acc-1")

    async def test_a_write_that_did_not_persist_is_an_error(self, store, monkeypatch):
        """A no-op upsert must not be reported as a saved policy."""

        async def _lost(account_id: str, key_name: str, value: str) -> None:
            return None

        monkeypatch.setattr("backend.db.accounts.upsert_credential", _lost)

        with pytest.raises(OutreachPolicyStoreUnavailableError, match="did not persist"):
            await set_outreach_policy("acc-1", mode=OUTREACH_CONFIRMED)

    async def test_an_unreadable_row_set_reports_unavailable(self, store, monkeypatch):
        async def _boom(account_id: str) -> list[Any]:
            raise RuntimeError("connection reset")

        monkeypatch.setattr("backend.db.accounts.list_credentials", _boom)

        with pytest.raises(OutreachPolicyStoreUnavailableError):
            await read_outreach_overrides("acc-1")


class TestClearFallsBackToTheDeployment:
    async def test_both_rows_are_deleted_and_the_deployment_default_applies(
        self, store, monkeypatch
    ):
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY
        store[("acc-1", DAILY_PROACTIVE_CAP_KEY)] = "1"
        monkeypatch.setenv(MODE_KEY, OUTREACH_CONFIRMED)

        policy = await clear_outreach_policy("acc-1")

        assert store == {}
        # Deployment default, not the safe default: the account rows are gone.
        assert policy.mode == OUTREACH_CONFIRMED
        # An opt-in with no declared budget keeps the historical bound.
        assert policy.daily_proactive_cap == 20

    async def test_clearing_an_unset_policy_is_idempotent(self, store):
        policy = await clear_outreach_policy("acc-1")

        assert store == {}
        assert policy.mode == OUTREACH_INBOUND
        assert policy.daily_proactive_cap == 0


class TestOverridesAreTheAccountRows:
    async def test_only_policy_keys_are_reported(self, store):
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY
        store[("acc-1", "XHS_COOKIE")] = "a1=cookie"

        overrides = await read_outreach_overrides("acc-1")

        assert overrides == {MODE_KEY: OUTREACH_NOBODY}

    async def test_no_pool_means_no_overrides_not_an_error(self, monkeypatch):
        monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

        assert await read_outreach_overrides("acc-1") == {}

    async def test_a_blank_account_has_no_overrides(self, store):
        store[("acc-1", MODE_KEY)] = OUTREACH_NOBODY

        assert await read_outreach_overrides("  ") == {}
