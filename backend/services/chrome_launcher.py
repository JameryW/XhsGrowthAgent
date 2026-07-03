"""Chrome launcher — manages N always-on per-account Chrome instances (CDP mode).

Each account that has a ``cdp_port`` binding gets its own dedicated Chrome process
launched with ``--user-data-dir=<profile> --remote-debugging-port=<port>``. The
publisher then ``connect_over_cdp``s to that port, attaching to the profile's own
login state (no cookie injection).

This module is the testable core: probe ports, clear stale SingletonLock files,
launch/stop Chrome. The thin bash wrapper ``scripts/chrome-profiles.sh`` calls
these functions for use outside the asyncio app (host-side, before/after deploy).

Design notes (see ``research/cdp-per-profile.md``):
- ``connect_over_cdp`` attaches as a DevTools client — it does NOT take the
  SingletonLock, so it's safe to attach while the Chrome is running.
- ``SingletonLock`` (a symlink → ``<host>-<pid>`` on Linux) only matters when
  *launching* a second Chrome on the same dir. We clear it only when the port
  is dead AND the lock's target PID is not alive.
- Chrome binary preference: ``google-chrome`` > ``google-chrome-stable`` >
  ``chromium`` (real branded Chrome has a different fingerprint baseline than
  Playwright's bundled chromium — relevant for XHS 反爬).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path

from backend.db.accounts import AccountRow

logger = logging.getLogger("xhs_growth.services.chrome_launcher")

# Chrome binary candidates, in preference order. Branded Chrome first (反爬),
# chromium as a last-resort fallback.
_CHROME_BIN_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)

# SingletonLock files Chrome writes into the user-data-dir to enforce
# single-instance-per-dir. All three are cleared together on a stale lock.
_SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

# Extra flags every per-account Chrome gets. --no-first-run /
# --no-default-browser-check suppress first-run UX that would block automation.
# --remote-debugging-address=0.0.0.0 makes the port reachable from inside the
# backend container (via host.containers.internal).
_DEFAULT_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--remote-debugging-address=0.0.0.0",
)


@dataclass
class ChromeStatus:
    """Result of probing/launching one account's Chrome."""

    account_id: str
    port: int
    profile_path: str
    alive: bool
    action: str  # "skipped" | "launched" | "lock_cleared" | "failed" | "stopped"
    message: str = ""


# ── Chrome binary discovery ──


def find_chrome_binary() -> str:
    """Return the first available Chrome binary path, or raise RuntimeError.

    Searches PATH for the candidates in preference order. Fails loud (not
    silent) so a deploy without Chrome installed surfaces immediately rather
    than silently launching nothing.
    """
    for name in _CHROME_BIN_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "No Chrome binary found. Install google-chrome / google-chrome-stable "
        "/ chromium, or set XHS_CHROME_BIN to an absolute path."
    )


def _resolve_chrome_bin() -> str:
    """Allow override via XHS_CHROME_BIN env, else auto-discover."""
    explicit = os.environ.get("XHS_CHROME_BIN", "").strip()
    if explicit:
        if not os.path.isfile(explicit) or not os.access(explicit, os.X_OK):
            raise RuntimeError(f"XHS_CHROME_BIN={explicit} is not an executable file")
        return explicit
    return find_chrome_binary()


# ── Port probing ──


async def probe_port(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Return True if a Chrome CDP server is answering on ``host:port``.

    A bare TCP connect can succeed when the port is held by a non-Chrome service
    or Chrome hasn't finished binding the DevTools server. We HTTP-GET
    ``/json/version`` and look for the ``Browser`` field — that's the canonical
    "Chrome is up and ready" signal.
    """
    import json
    import urllib.request

    url = f"http://{host}:{port}/json/version"
    loop = asyncio.get_running_loop()

    def _fetch() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status != 200:
                    return False
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                return "Browser" in data or "webSocketDebuggerUrl" in data
        except Exception:
            return False

    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception:
        return False


# ── SingletonLock handling ──


def _read_pidfile(profile_path: str) -> int | None:
    """Return the PID recorded in ``<profile>/chrome.pid``, or None if absent/unparseable."""
    pidfile = Path(profile_path) / "chrome.pid"
    try:
        return int(pidfile.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_pidfile(profile_path: str, pid: int) -> None:
    """Record the launched Chrome's PID so stop/stale-lock checks have a source of truth."""
    Path(profile_path).mkdir(parents=True, exist_ok=True)
    (Path(profile_path) / "chrome.pid").write_text(str(pid), encoding="utf-8")


def _clear_pidfile(profile_path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        (Path(profile_path) / "chrome.pid").unlink()


def _pid_alive(pid: int) -> bool:
    """Return True if ``pid`` is a running process.

    ``os.kill(pid, 0)`` is the POSIX probe — signal 0 checks existence without
    actually signalling.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _singleton_lock_pid(profile_path: str) -> int | None:
    """Extract the PID from the SingletonLock symlink target.

    Chrome writes ``SingletonLock`` as a symlink whose target is
    ``<hostname>-<pid>``. Returns the pid, or None if the lock is absent or
    doesn't follow that format.
    """
    lock = Path(profile_path) / "SingletonLock"
    try:
        target = os.readlink(lock)
    except (FileNotFoundError, OSError):
        return None
    # target looks like "hostname-12345"
    if "-" in target:
        _, _, pid_str = target.rpartition("-")
        try:
            return int(pid_str)
        except ValueError:
            return None
    return None


def clear_stale_lock(profile_path: str) -> bool:
    """Remove SingletonLock/Cookie/Socket when the Chrome that wrote them is dead.

    Returns True if any lock files were removed. **Never** call this when the
    port probe says Chrome is up — removing a live lock corrupts the profile.
    Safe to call when no lock exists (no-op).

    Decision tree:
      - SingletonLock absent → nothing to clear, return False
      - SingletonLock present, target PID alive → DO NOT clear (Chrome running)
      - SingletonLock present, target PID dead (or unreadable) → clear all three
    """
    lock = Path(profile_path) / "SingletonLock"
    if not lock.is_symlink() and not lock.exists():
        return False

    pid = _singleton_lock_pid(profile_path)
    if pid is not None and _pid_alive(pid):
        # A Chrome is running on this dir under that PID — leave the lock alone.
        logger.warning(
            "SingletonLock for %s points at live PID %d — not clearing",
            profile_path,
            pid,
        )
        return False

    removed_any = False
    for name in _SINGLETON_FILES:
        p = Path(profile_path) / name
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
                removed_any = True
        except OSError as e:
            logger.warning("Failed to remove %s: %s", p, e)
    if removed_any:
        logger.info("Cleared stale SingletonLock files in %s", profile_path)
    return removed_any


# ── Launch / stop ──


def _build_launch_cmd(
    chrome_bin: str, profile_path: str, port: int, headless: bool = False
) -> list[str]:
    """Construct the Chrome command line for a per-account instance.

    Uses ``create_subprocess_exec`` (not a shell) — args are passed directly to
    execve, so no shell-injection surface even if profile_path/port ever came
    from untrusted input (they don't — both are DB-stored, operator-controlled).
    """
    cmd = [
        chrome_bin,
        f"--user-data-dir={profile_path}",
        f"--remote-debugging-port={port}",
    ]
    cmd.extend(_DEFAULT_FLAGS)
    if headless:
        cmd.append("--headless=new")
    return cmd


async def ensure_chrome(
    account: AccountRow,
    *,
    headless: bool = False,
    chrome_bin: str | None = None,
) -> ChromeStatus:
    """Ensure the account's dedicated Chrome is running. Launch if down.

    Steps:
      1. HTTP-probe the port — if Chrome answers, skip (idempotent).
      2. If down, inspect SingletonLock: clear it only if its PID is dead.
         If the PID is alive (another Chrome holds the dir) skip — don't抢.
      3. Launch ``google-chrome --user-data-dir=… --remote-debugging-port=…``
         detached, write a pidfile.

    Returns a ChromeStatus describing what happened. Never raises — failures
    are reported as ``action="failed"`` so a bulk ``ensure_all`` keeps going.
    """
    if account.cdp_port <= 0 or not account.chrome_profile_path:
        return ChromeStatus(
            account_id=account.id,
            port=account.cdp_port,
            profile_path=account.chrome_profile_path,
            alive=False,
            action="failed",
            message="account has no cdp_port / chrome_profile_path binding",
        )

    port = account.cdp_port
    profile_path = account.chrome_profile_path
    Path(profile_path).mkdir(parents=True, exist_ok=True)

    # 1. Already up?
    if await probe_port(port):
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=True,
            action="skipped",
            message="chrome already running on port",
        )

    # 2. Stale lock?
    cleared = clear_stale_lock(profile_path)
    # Re-probe after lock clear — a live Chrome that just hadn't bound the port
    # yet would have been misjudged as down. If the lock's PID is alive we
    # returned False above and didn't clear, so this is safe.
    if cleared and await probe_port(port):
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=True,
            action="skipped",
            message="chrome came up after lock clear",
        )

    # If the lock is still present (PID alive), a Chrome holds the dir but
    # isn't answering on the port — don't launch a second one.
    lock_pid = _singleton_lock_pid(profile_path)
    if lock_pid is not None and _pid_alive(lock_pid):
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message=(
                f"SingletonLock held by live PID {lock_pid} but port {port} "
                "not answering — refusing to launch a second Chrome"
            ),
        )

    # 3. Launch.
    try:
        bin_ = chrome_bin or _resolve_chrome_bin()
    except RuntimeError as e:
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message=str(e),
        )

    cmd = _build_launch_cmd(bin_, profile_path, port, headless=headless)
    try:
        # start_new_session=True detaches the Chrome from this process group
        # so it survives the launcher (and the shell that ran it) exiting.
        # create_subprocess_exec (not a shell) — args go straight to execve.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message=f"launch failed: {e}",
        )

    _write_pidfile(profile_path, proc.pid)
    logger.info(
        "Launched Chrome for account %s on port %d (pid %d, profile %s)",
        account.id,
        port,
        proc.pid,
        profile_path,
    )

    # Give Chrome a moment to bind the DevTools port. We don't block long —
    # the publisher's connect_over_cdp has its own retry/timeout, and a
    # short probe here just gives the status report a better answer.
    await asyncio.sleep(0.5)
    alive = await probe_port(port)
    return ChromeStatus(
        account_id=account.id,
        port=port,
        profile_path=profile_path,
        alive=alive,
        action="launched",
        message=f"pid={proc.pid}, port_up={alive}",
    )


async def stop_chrome(account: AccountRow) -> ChromeStatus:
    """Stop the account's Chrome via its pidfile. SIGTERM, then SIGKILL on timeout.

    Clears the pidfile and stale SingletonLock files afterward. Safe to call
    when Chrome is already down (cleans up leftover lock files).
    """
    port = account.cdp_port
    profile_path = account.chrome_profile_path
    if not profile_path:
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message="no chrome_profile_path",
        )

    pid = _read_pidfile(profile_path)
    if pid is None or not _pid_alive(pid):
        # Already down — just tidy any stale locks.
        clear_stale_lock(profile_path)
        _clear_pidfile(profile_path)
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="stopped",
            message="chrome not running (pidfile absent or pid dead)",
        )

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as e:
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message=f"SIGTERM failed: {e}",
        )

    # Wait for the process to actually exit (it owns the port + SingletonLock).
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if not _pid_alive(pid):
            break
        await asyncio.sleep(0.2)

    if _pid_alive(pid):
        # SIGTERM didn't take — escalate.
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGKILL)
        await asyncio.sleep(0.3)

    alive = _pid_alive(pid)
    clear_stale_lock(profile_path)
    _clear_pidfile(profile_path)
    return ChromeStatus(
        account_id=account.id,
        port=port,
        profile_path=profile_path,
        alive=alive,
        action="stopped" if not alive else "failed",
        message=f"pid={pid}, still_alive={alive}",
    )


# ── Bulk helpers (used by the bash wrapper) ──


async def ensure_all(
    accounts: list[AccountRow],
    *,
    headless: bool = False,
    chrome_bin: str | None = None,
) -> list[ChromeStatus]:
    """Ensure Chrome is up for every account that has a port binding.

    Accounts without ``cdp_port``/``chrome_profile_path`` are skipped (they
    fall back to the global CDP endpoint at publish time). Run concurrently —
    each Chrome launches independently.
    """
    targets = [a for a in accounts if a.is_active and a.cdp_port > 0 and a.chrome_profile_path]
    if not targets:
        return []
    return await asyncio.gather(
        *(ensure_chrome(a, headless=headless, chrome_bin=chrome_bin) for a in targets)
    )


async def stop_all(accounts: list[AccountRow]) -> list[ChromeStatus]:
    """Stop Chrome for every account that has a profile binding."""
    targets = [a for a in accounts if a.chrome_profile_path]
    if not targets:
        return []
    return await asyncio.gather(*(stop_chrome(a) for a in targets))


async def status_all(accounts: list[AccountRow]) -> list[ChromeStatus]:
    """Probe each account's port — read-only, no launch/stop."""
    targets = [a for a in accounts if a.chrome_profile_path and a.cdp_port > 0]

    async def _probe(a: AccountRow) -> ChromeStatus:
        alive = await probe_port(a.cdp_port)
        return ChromeStatus(
            account_id=a.id,
            port=a.cdp_port,
            profile_path=a.chrome_profile_path,
            alive=alive,
            action="skipped",
            message="alive" if alive else "down",
        )

    return await asyncio.gather(*(_probe(a) for a in targets))


def format_status_table(statuses: list[ChromeStatus]) -> str:
    """Render statuses as a plain-text table for CLI / bash wrapper output."""
    if not statuses:
        return "(no accounts with chrome profile bindings)"
    header = f"{'ACCOUNT':<36} {'PORT':<6} {'STATE':<8} {'ACTION':<14} MESSAGE"
    lines = [header, "-" * len(header)]
    for s in statuses:
        state = "alive" if s.alive else "down"
        lines.append(f"{s.account_id:<36} {s.port:<6} {state:<8} {s.action:<14} {s.message}")
    return "\n".join(lines)


__all__ = [
    "ChromeStatus",
    "clear_stale_lock",
    "ensure_all",
    "ensure_chrome",
    "find_chrome_binary",
    "format_status_table",
    "probe_port",
    "status_all",
    "stop_all",
    "stop_chrome",
]


# ── CLI entry (called by scripts/chrome-profiles.sh) ──
#
# ``python3 -m backend.services.chrome_launcher <start|status|stop>`` loads the
# accounts list from the DB (via backend.db.accounts.list_accounts) and runs the
# matching bulk op. The bash wrapper is intentionally thin — it just forwards
# the subcommand so operators don't need to remember the python invocation.
#
# DB connectivity: this runs on the host (Chrome lives on the host), but the DB
# is in the postgres-xhs container. POSTGRES_URI must be reachable from the host
# (deploy.sh publishes 5432 on the host, so localhost:5432 works). If the pool
# isn't ready, every subcommand degrades gracefully — status reports "no
# accounts", start/stop report nothing to do.


async def _load_accounts() -> list[AccountRow]:
    """Load all accounts from the DB.

    Returns [] on any DB failure (host can't reach the container, pool not
    initialized, etc.) so the CLI never crashes on a missing DB — it just
    reports nothing to do.
    """
    from backend.db.pool import init_pool, is_pool_ready

    if not is_pool_ready():
        try:
            await init_pool()
        except Exception as e:  # noqa: BLE001 — degrade, don't crash the CLI
            logger.warning("chrome-launcher CLI: DB pool init failed: %s", e)
            return []

    if not is_pool_ready():
        return []
    try:
        from backend.db.accounts import list_accounts

        return await list_accounts()
    except Exception as e:  # noqa: BLE001 — degrade, don't crash the CLI
        logger.warning("chrome-launcher CLI: list_accounts failed: %s", e)
        return []


async def _cli(subcommand: str, headless: bool) -> int:
    """Run the requested bulk op against all accounts. Returns exit code."""
    accounts = await _load_accounts()
    if subcommand == "start":
        statuses = await ensure_all(accounts, headless=headless)
    elif subcommand == "status":
        statuses = await status_all(accounts)
    elif subcommand == "stop":
        statuses = await stop_all(accounts)
    else:  # pragma: no cover — argparse choices() rejects this
        print(f"unknown subcommand: {subcommand} (use start|status|stop)")
        return 2

    print(format_status_table(statuses))
    # Exit non-zero if any account failed to launch/stop — operator should see it.
    failed = [s for s in statuses if s.action == "failed"]
    return 1 if failed else 0


def main() -> None:
    """CLI entry: ``python -m backend.services.chrome_launcher <start|status|stop>``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="chrome-launcher",
        description="Manage per-account always-on Chrome instances (CDP multi-profile).",
    )
    parser.add_argument(
        "subcommand",
        choices=("start", "status", "stop"),
        help="start=launch/keepalive, status=probe ports, stop=SIGTERM all",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="launch Chrome with --headless=new (default: headed, for 扫码 login)",
    )
    args = parser.parse_args()

    import asyncio

    from backend.db.pool import close_pool

    try:
        code = asyncio.run(_cli(args.subcommand, args.headless))
    finally:
        with contextlib.suppress(Exception):  # noqa: BLE001 — best-effort cleanup on the way out
            asyncio.run(close_pool())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
