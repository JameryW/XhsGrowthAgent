"""Tests for chrome_launcher — the testable core of the CDP multi-profile launcher.

Covers: port probing (HTTP /json/version), SingletonLock stale-vs-live handling,
ensure_chrome launch/skip/fail paths, stop_chrome SIGTERM/SIGKILL, and the bulk
helpers' filtering. All OS/subprocess surface is mocked — no real Chrome runs.
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.accounts import AccountRow
from backend.services import chrome_launcher as cl
from backend.services.chrome_launcher import (
    ChromeStatus,
    clear_stale_lock,
    ensure_all,
    ensure_chrome,
    find_chrome_binary,
    format_status_table,
    probe_port,
    status_all,
    stop_all,
    stop_chrome,
)

# ── Account fixture ──


def _account(
    port: int = 9223, profile: str = "/tmp/xhs-test-profile-xyz", active: bool = True
) -> AccountRow:
    return AccountRow(
        id="acc-1",
        name="acc",
        is_active=active,
        cdp_port=port,
        chrome_profile_path=profile,
    )


@pytest.fixture
def _profile_dir(tmp_path: Path) -> Path:
    """A fresh throwaway profile dir for lock/pidfile tests."""
    d = tmp_path / "profile-acc-1"
    d.mkdir()
    return d


# ── probe_port ──


@pytest.mark.asyncio
async def test_probe_port_returns_true_when_chrome_answers():
    """A 200 with a Browser field → True (Chrome is up)."""
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    fake_resp.read.return_value = b'{"Browser": "Chrome/120.0", "webSocketDebuggerUrl": "ws://..."}'

    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = await probe_port(9223)
    assert result is True


@pytest.mark.asyncio
async def test_probe_port_returns_false_on_non_chrome_response():
    """A 200 without Browser/webSocketDebuggerUrl → False (port held by non-Chrome)."""
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    fake_resp.read.return_value = b'{"unrelated": "service"}'

    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = await probe_port(9223)
    assert result is False


@pytest.mark.asyncio
async def test_probe_port_returns_false_on_connection_error():
    """Port not listening → urllib raises → False."""
    with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
        result = await probe_port(9999)
    assert result is False


@pytest.mark.asyncio
async def test_probe_port_returns_false_on_non_200():
    fake_resp = MagicMock()
    fake_resp.status = 404
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = await probe_port(9223)
    assert result is False


def test_list_cdp_targets_filters_malformed_values():
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    fake_resp.read.return_value = b'[{"id":"blank","type":"page","url":"about:blank"},{"id":1},{}]'

    with patch("urllib.request.urlopen", return_value=fake_resp):
        targets = cl._list_cdp_targets(9223)

    assert targets == [cl.CdpTarget("blank", "page", "about:blank")]


def test_blank_page_candidates_retain_one_page():
    targets = [
        cl.CdpTarget("blank-1", "page", "about:blank"),
        cl.CdpTarget("new-tab", "page", "chrome://newtab/"),
        cl.CdpTarget("worker", "service_worker", "https://example.com/sw.js"),
    ]

    page_count, candidates = cl._blank_page_cleanup_candidates(targets)

    assert page_count == 2
    assert candidates == [targets[0]]


@pytest.mark.asyncio
async def test_prune_blank_pages_dry_run_never_closes(_profile_dir, monkeypatch):
    targets = [
        cl.CdpTarget("business", "page", "https://creator.xiaohongshu.com/new/home"),
        cl.CdpTarget("blank", "page", "about:blank"),
    ]
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "_has_active_cdp_connection", lambda port: False)
    monkeypatch.setattr(cl, "_list_cdp_targets", lambda port: targets)
    close = MagicMock(return_value=True)
    monkeypatch.setattr(cl, "_close_cdp_target", close)

    statuses = await cl.prune_blank_pages_all([_account(profile=str(_profile_dir))])

    assert statuses[0].action == "dry_run"
    assert statuses[0].candidate_count == 1
    close.assert_not_called()


@pytest.mark.asyncio
async def test_prune_blank_pages_skips_active_cdp_connection(_profile_dir, monkeypatch):
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "_has_active_cdp_connection", lambda port: True)
    targets = MagicMock()
    monkeypatch.setattr(cl, "_list_cdp_targets", targets)

    statuses = await cl.prune_blank_pages_all([_account(profile=str(_profile_dir))])

    assert statuses[0].action == "skipped"
    assert "active" in statuses[0].message
    targets.assert_not_called()


@pytest.mark.asyncio
async def test_prune_blank_pages_apply_requires_account_selection():
    with pytest.raises(ValueError, match="requires at least one account id"):
        await cl.prune_blank_pages_all([_account()], apply=True)


@pytest.mark.asyncio
async def test_prune_blank_pages_apply_rechecks_and_closes_one(_profile_dir, monkeypatch):
    business = cl.CdpTarget("business", "page", "https://creator.xiaohongshu.com/new/home")
    blank = cl.CdpTarget("blank", "page", "chrome://newtab/")
    list_targets = MagicMock(side_effect=[[business, blank], [business, blank], [business]])
    close = MagicMock(return_value=True)
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "_has_active_cdp_connection", lambda port: False)
    monkeypatch.setattr(cl, "_list_cdp_targets", list_targets)
    monkeypatch.setattr(cl, "_close_cdp_target", close)

    statuses = await cl.prune_blank_pages_all(
        [_account(profile=str(_profile_dir))], apply=True, account_ids=["acc-1"]
    )

    assert statuses[0].action == "cleaned"
    assert statuses[0].closed_count == 1
    close.assert_called_once_with(9223, "blank")
    assert list_targets.call_count == 3


@pytest.mark.asyncio
async def test_cli_rejects_global_page_prune_apply(monkeypatch, capsys):
    monkeypatch.setattr(cl, "_load_accounts", AsyncMock(return_value=[]))
    prune = AsyncMock()
    monkeypatch.setattr(cl, "prune_blank_pages_all", prune)

    code = await cl._cli("prune-pages", apply_cleanup=True)

    assert code == 2
    assert "requires at least one --account-id" in capsys.readouterr().out
    prune.assert_not_awaited()


# ── clear_stale_lock ──


def test_clear_stale_lock_no_lock_returns_false(_profile_dir: Path):
    """No SingletonLock → nothing to clear, returns False."""
    assert clear_stale_lock(str(_profile_dir)) is False


def test_clear_stale_lock_removes_dead_pid_lock(_profile_dir: Path, monkeypatch):
    """Lock present, target PID dead → all three Singleton files removed."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("testhost-99999", lock)  # PID 99999 almost certainly dead
    (_profile_dir / "SingletonCookie").write_text("x")
    (_profile_dir / "SingletonSocket").write_text("y")

    monkeypatch.setattr(cl, "_pid_alive", lambda pid: False)

    result = clear_stale_lock(str(_profile_dir))
    assert result is True
    assert not lock.exists()
    assert not (_profile_dir / "SingletonCookie").exists()
    assert not (_profile_dir / "SingletonSocket").exists()


def test_clear_stale_lock_keeps_live_pid_lock(_profile_dir: Path, monkeypatch):
    """Lock present, target PID alive → DO NOT clear (Chrome running on that dir)."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("testhost-12345", lock)
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: True)

    result = clear_stale_lock(str(_profile_dir))
    assert result is False
    assert lock.is_symlink()  # untouched


def test_clear_stale_lock_unparseable_pid_clears(_profile_dir: Path, monkeypatch):
    """Lock symlink target doesn't match hostname-<pid> format → treat as stale, clear."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("not-a-pid-format", lock)
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: True)  # even if called, won't be

    result = clear_stale_lock(str(_profile_dir))
    assert result is True
    assert not lock.exists()


# ── _singleton_lock_pid ──


def test_singleton_lock_pid_extracts_pid(_profile_dir: Path):
    os.symlink("myhost-4242", _profile_dir / "SingletonLock")
    assert cl._singleton_lock_pid(str(_profile_dir)) == 4242


def test_singleton_lock_pid_none_when_absent(_profile_dir: Path):
    assert cl._singleton_lock_pid(str(_profile_dir)) is None


def test_singleton_lock_pid_none_when_unparseable(_profile_dir: Path):
    os.symlink("no-dash-here", _profile_dir / "SingletonLock")
    assert cl._singleton_lock_pid(str(_profile_dir)) is None


def test_raw_cmdline_has_profile_supports_null_and_space_delimiters():
    profile = "/test/xhs/.chrome-profiles/acc"
    option = b"--user-data-dir=/test/xhs/.chrome-profiles/acc"

    assert cl._raw_cmdline_has_profile(b"/opt/chrome\x00" + option + b"\x00", profile)
    assert cl._raw_cmdline_has_profile(b"/opt/chrome " + option + b" --flag", profile)
    assert not cl._raw_cmdline_has_profile(
        b"/opt/chrome --user-data-dir=/test/xhs/.chrome-profiles/acc-other", profile
    )


# ── ensure_chrome ──


@pytest.mark.asyncio
async def test_ensure_chrome_skips_when_port_alive(_profile_dir: Path, monkeypatch):
    """Port already answering → action=skipped, no launch."""
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    launch = AsyncMock()
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "skipped"
    assert status.alive is True
    launch.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_chrome_launches_when_down_and_no_lock(_profile_dir: Path, monkeypatch):
    """Port down, no lock → launch Chrome, write pidfile."""
    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, False, True, False, True]))
    monkeypatch.setattr(cl, "_resolve_chrome_bin", lambda: "/usr/bin/google-chrome")
    forwarder = AsyncMock()
    monkeypatch.setattr(cl, "_ensure_socat_forwarder", forwarder)

    fake_proc = MagicMock()
    fake_proc.pid = 12345
    launch = AsyncMock(return_value=fake_proc)
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "launched"
    assert status.alive is True
    assert status.port == 9223
    launch.assert_awaited_once()
    forwarder.assert_awaited_once_with(str(_profile_dir), 9223)
    # pidfile written
    assert (_profile_dir / "chrome.pid").read_text() == "12345"


@pytest.mark.asyncio
async def test_ensure_chrome_repairs_forwarder_when_internal_port_alive(
    _profile_dir: Path, monkeypatch
):
    """Public port down but internal Chrome alive → repair socat before lock logic."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-11111", lock)

    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, True, False, True]))
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: True)
    forwarder = AsyncMock()
    monkeypatch.setattr(cl, "_ensure_socat_forwarder", forwarder)
    launch = AsyncMock()
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "skipped"
    assert status.alive is True
    assert "public forwarder ready" in status.message
    forwarder.assert_awaited_once_with(str(_profile_dir), 9223)
    launch.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_chrome_clears_stale_lock_then_launches(_profile_dir: Path, monkeypatch):
    """Port down, stale lock present → clear it, then launch."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-99998", lock)

    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, False, False, True, True]))
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: False)  # lock PID dead
    monkeypatch.setattr(cl, "_resolve_chrome_bin", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(cl, "_ensure_socat_forwarder", AsyncMock())
    fake_proc = MagicMock()
    fake_proc.pid = 22222
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", AsyncMock(return_value=fake_proc))
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "launched"
    assert not lock.exists()  # stale lock cleared


@pytest.mark.asyncio
async def test_ensure_chrome_refuses_when_live_lock_holds_dir(_profile_dir: Path, monkeypatch):
    """Port down but SingletonLock PID alive → refuse to launch a second Chrome."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-11111", lock)

    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, False]))
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: True)  # lock PID alive
    launch = AsyncMock()
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "failed"
    assert "live PID" in status.message
    launch.assert_not_called()  # must NOT launch a second Chrome on the same dir


@pytest.mark.asyncio
async def test_ensure_chrome_fails_when_no_binding(monkeypatch):
    """Account with cdp_port=0 / empty profile → action=failed, no probe, no launch."""
    probe = AsyncMock()
    monkeypatch.setattr(cl, "probe_port", probe)
    launch = AsyncMock()
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)

    account = AccountRow(id="acc", name="acc", cdp_port=0, chrome_profile_path="")
    status = await ensure_chrome(account)

    assert status.action == "failed"
    probe.assert_not_awaited()
    launch.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_chrome_fails_when_no_chrome_binary(_profile_dir: Path, monkeypatch):
    """Port down, no lock, but no Chrome binary installed → action=failed with message."""
    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, False]))

    def _no_chrome() -> str:
        raise RuntimeError("No Chrome binary found")

    monkeypatch.setattr(cl, "_resolve_chrome_bin", _no_chrome)
    launch = AsyncMock()
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "failed"
    assert "No Chrome binary" in status.message
    launch.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_chrome_fails_on_launch_oserror(_profile_dir: Path, monkeypatch):
    """create_subprocess_exec raises OSError → action=failed, no pidfile written."""
    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[False, False]))
    monkeypatch.setattr(cl, "_resolve_chrome_bin", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(
        cl.asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=OSError("no such binary")),
    )

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "failed"
    assert "launch failed" in status.message


# ── stop_chrome ──


@pytest.mark.asyncio
async def test_stop_chrome_sigterms_live_pid(_profile_dir: Path, monkeypatch):
    """pidfile present, PID alive → SIGTERM, wait, clear pidfile + lock."""
    (_profile_dir / "chrome.pid").write_text("4242")

    # First _pid_alive check (pidfile alive?) returns True so we reach SIGTERM;
    # subsequent checks (after SIGTERM, in the wait loop) return False.
    call_count = {"n": 0}

    def _fake_alive(pid: int) -> bool:
        call_count["n"] += 1
        return call_count["n"] == 1  # alive only on the first check

    monkeypatch.setattr(cl, "_pid_alive", _fake_alive)

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        os,
        "kill",
        lambda pid, sig: killed.append((pid, sig)),
    )
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await stop_chrome(account)

    assert status.action == "stopped"
    assert (4242, signal.SIGTERM) in killed
    assert not (_profile_dir / "chrome.pid").exists()


@pytest.mark.asyncio
async def test_stop_chrome_escalates_to_sigkill(_profile_dir: Path, monkeypatch):
    """SIGTERM doesn't kill the process within the deadline → SIGKILL."""
    (_profile_dir / "chrome.pid").write_text("5555")

    # _pid_alive stays True through the wait-loop (process won't die), then
    # True after the loop (→ SIGKILL escalation), then False after the SIGKILL
    # sleep (→ action="stopped", not "failed"). Order of calls:
    #   1. initial pidfile check  → True  (reach SIGTERM)
    #   2. in-loop body check     → True  (no break, loop exits via deadline)
    #   3. post-loop check        → True  (→ SIGKILL escalation)
    #   4. after SIGKILL sleep    → False (→ action="stopped")
    alive_checks = [True, True, True, False]

    def _fake_alive(pid: int) -> bool:
        return alive_checks.pop(0) if alive_checks else False

    monkeypatch.setattr(cl, "_pid_alive", _fake_alive)
    monkeypatch.setattr(cl, "_pid_matches_profile", lambda _pid, _profile: True)

    # Loop time advances past the 5.0s deadline so the while-loop exits via
    # condition (not break) — proving the process survived SIGTERM.
    time_seq = iter([0.0, 0.0, 0.0, 10.0])  # deadline calc, loop entry, loop recheck
    fake_loop = MagicMock()
    fake_loop.time = MagicMock(side_effect=lambda: next(time_seq))
    monkeypatch.setattr(cl.asyncio, "get_running_loop", lambda: fake_loop)

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await stop_chrome(account)

    assert status.action == "stopped"
    assert (5555, signal.SIGTERM) in sent
    assert (5555, signal.SIGKILL) in sent


@pytest.mark.asyncio
async def test_stop_chrome_no_pidfile_cleans_locks(_profile_dir: Path, monkeypatch):
    """No pidfile (Chrome already gone) → tidy stale locks, action=stopped."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-99997", lock)
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: False)

    account = _account(profile=str(_profile_dir))
    status = await stop_chrome(account)

    assert status.action == "stopped"
    assert not lock.exists()


@pytest.mark.asyncio
async def test_stop_chrome_dead_pid_in_pidfile_cleans(_profile_dir: Path, monkeypatch):
    """pidfile present but PID dead → treat as already-down, clean locks."""
    (_profile_dir / "chrome.pid").write_text("8888")
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-8888", lock)
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: False)

    account = _account(profile=str(_profile_dir))
    status = await stop_chrome(account)

    assert status.action == "stopped"
    assert not lock.exists()
    assert not (_profile_dir / "chrome.pid").exists()


@pytest.mark.asyncio
async def test_stop_chrome_fails_without_profile(monkeypatch):
    """Account with no chrome_profile_path → action=failed."""
    account = AccountRow(id="acc", name="acc", cdp_port=9223, chrome_profile_path="")
    status = await stop_chrome(account)
    assert status.action == "failed"
    assert "no chrome_profile_path" in status.message


# ── Bulk helpers ──


@pytest.mark.asyncio
async def test_ensure_all_filters_unbound_accounts(monkeypatch):
    """Accounts without port/profile/is_active are skipped; only bound+active launch."""
    launched: list[AccountRow] = []

    async def _fake_ensure(a: AccountRow, *, chrome_bin: str | None = None) -> ChromeStatus:
        launched.append(a)
        return ChromeStatus(a.id, a.cdp_port, a.chrome_profile_path, True, "launched")

    monkeypatch.setattr(cl, "ensure_chrome", _fake_ensure)

    accounts = [
        _account(port=9223, profile="/p/a", active=True),  # launches
        _account(port=0, profile="", active=True),  # skipped: no binding
        _account(port=9224, profile="/p/c", active=False),  # skipped: inactive
        AccountRow(
            id="d", name="d", cdp_port=9225, chrome_profile_path="/p/d", is_active=True
        ),  # launches
    ]
    statuses = await ensure_all(accounts)

    assert len(statuses) == 2
    assert {s.account_id for s in statuses} == {"acc-1", "d"}


@pytest.mark.asyncio
async def test_ensure_all_empty_when_none_bound():
    """No accounts with bindings → empty list, no work."""
    accounts = [AccountRow(id="a", name="a", cdp_port=0, chrome_profile_path="")]
    assert await ensure_all(accounts) == []


@pytest.mark.asyncio
async def test_stop_all_stops_all_with_profile(monkeypatch):
    """stop_all runs against every account with a profile_path (active or not)."""
    stopped: list[str] = []

    async def _fake_stop(a: AccountRow) -> ChromeStatus:
        stopped.append(a.id)
        return ChromeStatus(a.id, a.cdp_port, a.chrome_profile_path, False, "stopped")

    monkeypatch.setattr(cl, "stop_chrome", _fake_stop)

    accounts = [
        AccountRow(id="a", name="a", cdp_port=9223, chrome_profile_path="/p/a", is_active=True),
        AccountRow(
            id="b", name="b", cdp_port=0, chrome_profile_path="", is_active=False
        ),  # no profile
        AccountRow(
            id="c", name="c", cdp_port=9224, chrome_profile_path="/p/c", is_active=False
        ),  # has profile
    ]
    await stop_all(accounts)
    assert stopped == ["a", "c"]


@pytest.mark.asyncio
async def test_status_all_probes_bound_accounts(monkeypatch):
    """status_all probes each account with port+profile, returns ChromeStatus list."""
    monkeypatch.setattr(cl, "probe_port", AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(
        cl,
        "_safe_cache_bytes",
        lambda profile: {"/p/a": 1024, "/p/b": 0}[profile],
    )

    monkeypatch.delenv("XHS_CHROME_MEMORY_WARNING_MB", raising=False)
    monkeypatch.setattr(
        cl,
        "_profile_chrome_resources_for_profiles",
        lambda profiles: {"/p/a": (3, 4 * 1024**2), "/p/b": None},
    )

    accounts = [
        AccountRow(id="a", name="a", cdp_port=9223, chrome_profile_path="/p/a", is_active=True),
        AccountRow(id="b", name="b", cdp_port=9224, chrome_profile_path="/p/b", is_active=True),
        AccountRow(
            id="c", name="c", cdp_port=0, chrome_profile_path="/p/c", is_active=True
        ),  # no port, skipped
    ]
    statuses = await status_all(accounts)

    assert len(statuses) == 2
    assert statuses[0].alive is True
    assert statuses[1].alive is False
    assert statuses[0].message == (
        "alive; safe_cache=1.0KiB; chrome_processes=3; chrome_rss=4.0MiB"
    )
    assert statuses[1].message == "down; safe_cache=0B; chrome_resources=unknown"


@pytest.mark.asyncio
async def test_status_all_without_targets_skips_procfs_snapshot(monkeypatch):
    resources = MagicMock()
    monkeypatch.setattr(cl, "_profile_chrome_resources_for_profiles", resources)

    assert await status_all([]) == []
    resources.assert_not_called()


def test_process_tree_rss_bytes_aggregates_descendants(monkeypatch):
    monkeypatch.setattr(cl, "_iter_process_ids", lambda: iter([10, 11, 12, 99]))
    monkeypatch.setattr(
        cl,
        "_process_parent_and_rss_bytes",
        lambda pid: {
            10: (1, 100),
            11: (10, 200),
            12: (11, 300),
            99: (1, 400),
        }[pid],
    )

    assert cl._process_tree_rss_bytes(10) == (3, 600)


def test_profile_resources_for_profiles_shares_one_procfs_snapshot(monkeypatch):
    process_snapshot = {10: (1, 100)}
    snapshot = MagicMock(return_value=process_snapshot)
    seen_snapshots: list[dict[int, tuple[int, int]]] = []

    def _fake_resources(
        profile: str, *, process_snapshot: dict[int, tuple[int, int]] | None = None
    ) -> tuple[int, int]:
        assert process_snapshot is not None
        seen_snapshots.append(process_snapshot)
        return 1, 100

    monkeypatch.setattr(cl, "_process_stats_snapshot", snapshot)
    monkeypatch.setattr(cl, "_profile_chrome_resources", _fake_resources)

    resources = cl._profile_chrome_resources_for_profiles(["/p/a", "/p/b"])

    assert resources == {"/p/a": (1, 100), "/p/b": (1, 100)}
    snapshot.assert_called_once_with()
    assert seen_snapshots == [process_snapshot, process_snapshot]


def test_profile_chrome_resources_rejects_untrusted_pidfile(monkeypatch):
    monkeypatch.setattr(cl, "_read_pidfile", lambda profile: 123)
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(cl, "_pid_matches_profile", lambda pid, profile: False)
    process_tree = MagicMock()
    monkeypatch.setattr(cl, "_process_tree_rss_bytes", process_tree)

    assert cl._profile_chrome_resources("/p/acc") is None
    process_tree.assert_not_called()


@pytest.mark.asyncio
async def test_status_all_marks_memory_threshold_warning(monkeypatch):
    monkeypatch.setenv("XHS_CHROME_MEMORY_WARNING_MB", "4")
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "_safe_cache_bytes", lambda profile: 0)
    monkeypatch.setattr(
        cl,
        "_profile_chrome_resources_for_profiles",
        lambda profiles: {"/tmp/xhs-test-profile-xyz": (2, 4 * 1024**2)},
    )

    statuses = await status_all([_account()])

    assert statuses[0].message.endswith("chrome_rss=4.0MiB; memory=warning")


def test_memory_warning_threshold_disables_invalid_values(monkeypatch, caplog):
    monkeypatch.setenv("XHS_CHROME_MEMORY_WARNING_MB", "invalid")

    assert cl._memory_warning_threshold_bytes() is None
    assert "Invalid XHS_CHROME_MEMORY_WARNING_MB" in caplog.text


@pytest.mark.asyncio
async def test_profile_launch_lock_serializes_same_profile(tmp_path):
    """Two in-process callers cannot enter the same profile lifecycle lock."""
    profile = tmp_path / "profile"
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _holder():
        async with cl._profile_launch_lock(str(profile)):
            entered.set()
            await release.wait()

    async def _waiter():
        async with cl._profile_launch_lock(str(profile)):
            return True

    holder = asyncio.create_task(_holder())
    await entered.wait()
    waiter = asyncio.create_task(_waiter())
    await asyncio.sleep(0.05)
    assert not waiter.done()
    release.set()
    await holder
    assert await asyncio.wait_for(waiter, timeout=1) is True


@pytest.mark.asyncio
async def test_stop_chrome_refuses_pid_profile_mismatch(_profile_dir: Path, monkeypatch):
    """PID reuse must not let stop signal an unrelated process."""
    (_profile_dir / "chrome.pid").write_text("1234")
    monkeypatch.setattr(cl, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(cl, "_pid_matches_profile", lambda _pid, _profile: False)
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    status = await cl.stop_chrome(_account(profile=str(_profile_dir)))

    assert status.action == "failed"
    assert "does not belong" in status.message
    assert killed == []


@pytest.mark.asyncio
async def test_ensure_all_selects_requested_accounts(monkeypatch):
    launched: list[str] = []

    async def _fake_ensure(a: AccountRow, *, chrome_bin: str | None = None) -> ChromeStatus:
        launched.append(a.id)
        return ChromeStatus(a.id, a.cdp_port, a.chrome_profile_path, True, "skipped")

    monkeypatch.setattr(cl, "ensure_chrome", _fake_ensure)
    accounts = [
        _account(port=9223, profile="/p/a", active=True),
        AccountRow(id="b", name="b", is_active=True, cdp_port=9224, chrome_profile_path="/p/b"),
    ]

    statuses = await cl.ensure_all(accounts, account_ids=["b"])

    assert launched == ["b"]
    assert [status.account_id for status in statuses] == ["b"]


@pytest.mark.asyncio
async def test_reap_idle_keeps_active_cdp_connection(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "chrome.pid").write_text("1234")
    account = _account(profile=str(profile))
    monkeypatch.setattr(cl, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(cl, "_has_active_cdp_connection", lambda _port: True)
    stop = AsyncMock()
    monkeypatch.setattr(cl, "stop_chrome", stop)

    statuses = await cl.reap_idle([account], idle_seconds=1)

    assert statuses[0].action == "skipped"
    assert statuses[0].message == "active or unverified CDP connection"
    stop.assert_not_awaited()


def test_cleanup_profile_cache_preserves_login_data(tmp_path):
    profile = tmp_path / "profile"
    cache = profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "blob").write_bytes(b"cache")
    extra_caches = {
        profile / "Default" / "DawnGraphiteCache": b"dawn",
        profile / "component_crx_cache": b"component",
        profile / "optimization_guide_model_store": b"model",
    }
    for path, data in extra_caches.items():
        path.mkdir(parents=True)
        (path / "blob").write_bytes(data)
    cookies = profile / "Default" / "Cookies"
    cookies.write_bytes(b"login")

    cache_bytes, removed = cl.cleanup_profile_cache(str(profile))
    expected_cache_bytes = len(b"cache") + sum(len(data) for data in extra_caches.values())
    assert cache_bytes == expected_cache_bytes
    assert removed == 0
    assert (cache / "blob").exists()

    _, removed = cl.cleanup_profile_cache(str(profile), apply=True)
    assert removed == expected_cache_bytes
    assert not cache.exists()
    assert cookies.read_bytes() == b"login"


# ── find_chrome_binary ──


def test_find_chrome_binary_returns_first_available(monkeypatch):
    """Returns the first candidate found on PATH."""
    monkeypatch.setattr(
        cl.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "google-chrome" else None
    )
    assert find_chrome_binary() == "/usr/bin/google-chrome"


def test_find_chrome_binary_raises_when_none(monkeypatch):
    """No candidate on PATH → RuntimeError (fail loud, not silent)."""
    monkeypatch.setattr(cl.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="No Chrome binary"):
        find_chrome_binary()


def test_resolve_chrome_bin_env_override(monkeypatch):
    """XHS_CHROME_BIN env overrides auto-discovery."""
    monkeypatch.setenv("XHS_CHROME_BIN", "/opt/chrome/chrome")
    monkeypatch.setattr(os, "access", lambda _p, _m: True)
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    assert cl._resolve_chrome_bin() == "/opt/chrome/chrome"


# ── format_status_table ──


def test_format_status_table_empty():
    assert "no accounts" in format_status_table([])


def test_format_status_table_renders_rows():
    statuses = [
        ChromeStatus("acc-1", 9223, "/p/a", True, "skipped", "up"),
        ChromeStatus("acc-2", 9224, "/p/b", False, "failed", "no chrome"),
    ]
    out = format_status_table(statuses)
    assert "acc-1" in out and "acc-2" in out
    assert "alive" in out and "down" in out


# ── _build_launch_cmd ──


def test_build_launch_cmd_includes_core_flags(monkeypatch):
    """The launch command carries user-data-dir, internal port (cdp_port+OFFSET),
    and the default flags. Chrome listens on internal port (loopback only —
    Chrome 144 ignores --remote-debugging-address); socat exposes cdp_port."""
    monkeypatch.delenv("XHS_CHROME_CRASH_REPORTING", raising=False)
    monkeypatch.delenv("XHS_CHROME_DISK_CACHE_SIZE_MB", raising=False)
    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)
    assert "/usr/bin/google-chrome" in cmd
    assert "--user-data-dir=/p/acc" in cmd
    # Chrome binds the *internal* port (cdp_port + _INTERNAL_PORT_OFFSET);
    # socat maps the public cdp_port → internal. See _ensure_socat_forwarder.
    assert f"--remote-debugging-port={cl._internal_cdp_port(9223)}" in cmd
    assert "--remote-debugging-port=9223" not in cmd
    assert "--remote-debugging-address=0.0.0.0" in cmd
    assert "--remote-allow-origins=*" in cmd
    assert "--no-first-run" in cmd
    assert "--disk-cache-size=134217728" in cmd
    assert "--disable-crash-reporter" in cmd
    assert "--headless=new" not in cmd


def test_build_launch_cmd_allows_disk_cache_override(monkeypatch):
    monkeypatch.setenv("XHS_CHROME_DISK_CACHE_SIZE_MB", "64")

    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)

    assert "--disk-cache-size=67108864" in cmd


def test_build_launch_cmd_allows_default_cache(monkeypatch):
    monkeypatch.setenv("XHS_CHROME_DISK_CACHE_SIZE_MB", "0")

    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)

    assert not any(flag.startswith("--disk-cache-size=") for flag in cmd)


def test_build_launch_cmd_recovers_from_invalid_cache_setting(monkeypatch, caplog):
    monkeypatch.setenv("XHS_CHROME_DISK_CACHE_SIZE_MB", "not-a-number")

    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)

    assert "--disk-cache-size=134217728" in cmd
    assert "Invalid XHS_CHROME_DISK_CACHE_SIZE_MB" in caplog.text


def test_build_launch_cmd_recovers_from_negative_cache_setting(monkeypatch, caplog):
    monkeypatch.setenv("XHS_CHROME_DISK_CACHE_SIZE_MB", "-1")

    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)

    assert "--disk-cache-size=134217728" in cmd
    assert "Negative XHS_CHROME_DISK_CACHE_SIZE_MB" in caplog.text


def test_build_launch_cmd_can_enable_crash_reporting(monkeypatch):
    monkeypatch.setenv("XHS_CHROME_CRASH_REPORTING", "1")

    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223)

    assert "--disable-crash-reporter" not in cmd


def test_internal_cdp_port_offset():
    """Internal port = cdp_port + _INTERNAL_PORT_OFFSET (Chrome loopback port,
    socat forwards public cdp_port → internal)."""
    assert cl._internal_cdp_port(9223) == 9223 + cl._INTERNAL_PORT_OFFSET


def test_build_launch_cmd_bans_headless():
    """headless 已完全禁止：_build_launch_cmd 不再接受 headless 参数，
    任何调用路径都无法产出 --headless 标志。"""
    import inspect

    assert "headless" not in inspect.signature(cl._build_launch_cmd).parameters
    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p", 9223)
    assert not any(f.startswith("--headless") for f in cmd)


def test_hygiene_candidates_prefer_blanks_then_excess_creator():
    targets = [
        cl.CdpTarget("home", "page", "https://creator.xiaohongshu.com/new/home"),
        cl.CdpTarget("stats", "page", "https://creator.xiaohongshu.com/statistics/account/v2"),
        cl.CdpTarget("blank", "page", "about:blank"),
        cl.CdpTarget("blank2", "page", "chrome://newtab/"),
        cl.CdpTarget("other", "page", "https://www.xiaohongshu.com/explore"),
    ]
    page_count, candidates = cl._hygiene_page_cleanup_candidates(targets, max_pages=3)
    assert page_count == 5
    ids = [c.target_id for c in candidates]
    # Blanks first, then one excess creator tab (keep home preferred).
    assert "blank" in ids or "blank2" in ids
    assert "home" not in ids  # preferred creator tab retained
    assert len(candidates) >= 2


def test_hygiene_candidates_under_cap_only_return_blanks():
    targets = [
        cl.CdpTarget("home", "page", "https://creator.xiaohongshu.com/new/home"),
        cl.CdpTarget("blank", "page", "about:blank"),
    ]
    page_count, candidates = cl._hygiene_page_cleanup_candidates(targets, max_pages=6)
    assert page_count == 2
    assert [c.target_id for c in candidates] == ["blank"]


@pytest.mark.asyncio
async def test_hygiene_browser_pages_closes_multiple(_profile_dir, monkeypatch):
    home = cl.CdpTarget("home", "page", "https://creator.xiaohongshu.com/new/home")
    stats = cl.CdpTarget("stats", "page", "https://creator.xiaohongshu.com/statistics/account/v2")
    blank = cl.CdpTarget("blank", "page", "about:blank")
    # list → recheck → post-close
    list_targets = MagicMock(
        side_effect=[[home, stats, blank], [home, stats, blank], [home]]
    )
    close = MagicMock(return_value=True)
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "_has_active_cdp_connection", lambda port: False)
    monkeypatch.setattr(cl, "_list_cdp_targets", list_targets)
    monkeypatch.setattr(cl, "_close_cdp_target", close)

    statuses = await cl.hygiene_browser_pages_all(
        [_account(profile=str(_profile_dir))],
        apply=True,
        account_ids=["acc-1"],
        max_pages=2,
        max_close=3,
    )

    assert statuses[0].action == "cleaned"
    assert statuses[0].closed_count >= 1
    assert close.call_count >= 1
