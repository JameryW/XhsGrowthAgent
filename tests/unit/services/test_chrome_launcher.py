"""Tests for chrome_launcher — the testable core of the CDP multi-profile launcher.

Covers: port probing (HTTP /json/version), SingletonLock stale-vs-live handling,
ensure_chrome launch/skip/fail paths, stop_chrome SIGTERM/SIGKILL, and the bulk
helpers' filtering. All OS/subprocess surface is mocked — no real Chrome runs.
"""

from __future__ import annotations

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
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=False))
    monkeypatch.setattr(cl, "_resolve_chrome_bin", lambda: "/usr/bin/google-chrome")

    fake_proc = MagicMock()
    fake_proc.pid = 12345
    launch = AsyncMock(return_value=fake_proc)
    monkeypatch.setattr(cl.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(cl.asyncio, "sleep", AsyncMock())

    account = _account(profile=str(_profile_dir))
    status = await ensure_chrome(account)

    assert status.action == "launched"
    assert status.port == 9223
    launch.assert_awaited_once()
    # pidfile written
    assert (_profile_dir / "chrome.pid").read_text() == "12345"


@pytest.mark.asyncio
async def test_ensure_chrome_clears_stale_lock_then_launches(_profile_dir: Path, monkeypatch):
    """Port down, stale lock present → clear it, then launch."""
    lock = _profile_dir / "SingletonLock"
    os.symlink("host-99998", lock)

    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=False))
    monkeypatch.setattr(cl, "_pid_alive", lambda pid: False)  # lock PID dead
    monkeypatch.setattr(cl, "_resolve_chrome_bin", lambda: "/usr/bin/google-chrome")
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

    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=False))
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
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=False))

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
    monkeypatch.setattr(cl, "probe_port", AsyncMock(return_value=False))
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

    # Loop time advances past the 5.0s deadline so the while-loop exits via
    # condition (not break) — proving the process survived SIGTERM.
    time_seq = iter([0.0, 0.0, 10.0])  # deadline calc, loop entry, loop recheck
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

    async def _fake_ensure(
        a: AccountRow, *, headless: bool = False, chrome_bin: str | None = None
    ) -> ChromeStatus:
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


def test_build_launch_cmd_includes_core_flags():
    """The launch command carries user-data-dir, port, and the default flags."""
    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p/acc", 9223, headless=False)
    assert "/usr/bin/google-chrome" in cmd
    assert "--user-data-dir=/p/acc" in cmd
    assert "--remote-debugging-port=9223" in cmd
    assert "--remote-debugging-address=0.0.0.0" in cmd
    assert "--no-first-run" in cmd
    assert "--headless=new" not in cmd


def test_build_launch_cmd_headless_flag():
    cmd = cl._build_launch_cmd("/usr/bin/google-chrome", "/p", 9223, headless=True)
    assert "--headless=new" in cmd
