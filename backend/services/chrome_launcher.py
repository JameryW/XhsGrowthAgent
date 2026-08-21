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
import fcntl
import logging
import math
import os
import shutil
import signal
import time
from collections.abc import AsyncIterator, Iterable, Iterator
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

# A separate OS-level lock closes the race where two launcher CLI processes
# both see a down port before Chrome has created SingletonLock. The file itself
# is intentionally retained; flock releases it automatically on process exit.
_PROFILE_LAUNCH_LOCK_FILE = ".chrome-launch.lock"
_PROFILE_LOCK_TIMEOUT_SECONDS = 15.0

# Cache directories safe to remove after Chrome is stopped. Authentication and
# storage databases are deliberately not in this allowlist.
_SAFE_CACHE_DIR_NAMES = frozenset(
    {
        "Cache",
        "Code Cache",
        "DawnCache",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "GPUCache",
        "GrShaderCache",
        "Media Cache",
        "ShaderCache",
        "component_crx_cache",
        "extensions_crx_cache",
        "optimization_guide_model_store",
    }
)
_DEFAULT_IDLE_TIMEOUT_SECONDS = 1800.0
_DEFAULT_DISK_CACHE_SIZE_MB = 128
_DEFAULT_MEMORY_WARNING_MB = 0
_SAFE_BLANK_PAGE_URLS = frozenset({"about:blank", "chrome://newtab/"})

# Extra flags every per-account Chrome gets. --no-first-run /
# --no-default-browser-check suppress first-run UX that would block automation.
# --remote-debugging-address=0.0.0.0 makes the port reachable from inside the
# backend container (via host.containers.internal).
# --remote-allow-origins=* : Chrome 144 CDP rejects requests whose Host header
# doesn't match the bind address (returns 500). socat forwards container
# requests whose Host is host.containers.internal:9224 — chrome 19224 sees a
# mismatched Host and 500s. Allow all origins so CDP accepts the forwarded req.
_DEFAULT_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--remote-debugging-address=0.0.0.0",
    "--remote-allow-origins=*",
    # Ubuntu 23.10+ disables unprivileged user namespaces (apparmor_restrict_
    # unprivileged_userns=1) → Chrome FATAL "No usable sandbox". This host is
    # a headless automation worker (no untrusted web content), so --no-sandbox
    # is required for Chrome to start at all. Same flag as xhs_login.py uses.
    "--no-sandbox",
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


@dataclass
class ProfileCleanupStatus:
    """Result of a dry-run or applied safe-cache cleanup for one profile."""

    account_id: str
    profile_path: str
    cache_bytes: int
    removed_bytes: int
    action: str  # "dry_run" | "cleaned" | "skipped" | "failed"
    message: str = ""


@dataclass(frozen=True)
class CdpTarget:
    """Minimal validated target data read from a profile public CDP endpoint."""

    target_id: str
    target_type: str
    url: str


@dataclass
class PageCleanupStatus:
    """Result of a dry-run or applied blank-page cleanup for one profile."""

    account_id: str
    port: int
    page_count: int
    candidate_count: int
    closed_count: int
    action: str
    message: str = ""


@contextlib.asynccontextmanager
async def _profile_launch_lock(profile_path: str) -> AsyncIterator[None]:
    """Serialize launch/stop operations for one profile across processes."""
    lock_path = Path(profile_path) / _PROFILE_LAUNCH_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    deadline = asyncio.get_running_loop().time() + _PROFILE_LOCK_TIMEOUT_SECONDS
    try:
        while not acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for profile lock: {profile_path}"
                    ) from None
                await asyncio.sleep(0.05)
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(fd)


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
            headers = {}
            if host not in {"127.0.0.1", "localhost", "::1"}:
                headers["Host"] = f"127.0.0.1:{port}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def _cdp_http_get(port: int, path: str) -> bytes | None:
    """Read one public CDP HTTP endpoint, returning None on any uncertainty."""
    import urllib.request

    if port <= 0 or not path.startswith("/"):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
            return data if isinstance(data, bytes) else None
    except (OSError, ValueError):
        return None


def _list_cdp_targets(port: int) -> list[CdpTarget] | None:
    """Return validated CDP targets, or None if the endpoint cannot be trusted."""
    import json

    payload = _cdp_http_get(port, "/json/list")
    if payload is None:
        return None
    try:
        decoded: object = json.loads(payload.decode("utf-8", errors="replace"))
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, list):
        return None
    targets: list[CdpTarget] = []
    for item in decoded:
        if not isinstance(item, dict):
            continue
        target_id = item.get("id")
        target_type = item.get("type")
        target_url = item.get("url")
        if not isinstance(target_id, str):
            continue
        if not isinstance(target_type, str) or not isinstance(target_url, str):
            continue
        targets.append(CdpTarget(target_id, target_type, target_url))
    return targets


def _close_cdp_target(port: int, target_id: str) -> bool:
    """Ask Chrome to close one validated target via the public CDP endpoint."""
    import urllib.parse

    if not target_id:
        return False
    encoded_target_id = urllib.parse.quote(target_id, safe="")
    return _cdp_http_get(port, f"/json/close/{encoded_target_id}") is not None


def _blank_page_cleanup_candidates(targets: Iterable[CdpTarget]) -> tuple[int, list[CdpTarget]]:
    """Return safe blank-page candidates while always retaining one page target."""
    pages = [target for target in targets if target.target_type == "page"]
    if len(pages) <= 1:
        return len(pages), []
    blank_pages = [target for target in pages if target.url in _SAFE_BLANK_PAGE_URLS]
    return len(pages), blank_pages[: len(pages) - 1]


def _is_creator_center_url(url: str) -> bool:
    text = (url or "").lower()
    return "creator.xiaohongshu.com" in text and "login" not in text


def _hygiene_page_cleanup_candidates(
    targets: Iterable[CdpTarget],
    *,
    max_pages: int = 6,
) -> tuple[int, list[CdpTarget]]:
    """Candidates to close when a profile has too many open pages.

    Priority: blank/new-tab first, then excess Creator Center tabs (keep one).
    Always retains at least one page target so Chrome stays usable for humans.
    """
    pages = [target for target in targets if target.target_type == "page"]
    page_count = len(pages)
    if page_count <= 1:
        return page_count, []
    cap = max(1, int(max_pages or 1))
    blanks = [p for p in pages if p.url in _SAFE_BLANK_PAGE_URLS]
    creator = [p for p in pages if _is_creator_center_url(p.url)]

    # Prefer keeping a home/stats tab; close duplicate creator tabs first.
    def _creator_keep_score(t: CdpTarget) -> tuple[int, str]:
        url = t.url or ""
        preferred = any(
            token in url for token in ("/new/home", "/statistics/account", "/new/note-manager")
        )
        return (0 if preferred else 1, url)

    creator_sorted = sorted(creator, key=_creator_keep_score)
    excess_creator = creator_sorted[1:] if len(creator_sorted) > 1 else []
    ordered: list[CdpTarget] = []
    seen: set[str] = set()
    for candidate in blanks + excess_creator:
        if candidate.target_id in seen:
            continue
        seen.add(candidate.target_id)
        ordered.append(candidate)
    # If still over cap, allow closing other non-critical blanks already listed.
    max_close = max(0, page_count - 1)
    if page_count > cap:
        # Close enough to get under cap, but never more than max_close.
        need = min(max_close, page_count - cap)
        return page_count, ordered[: max(need, min(len(ordered), max_close))]
    # Under cap: still return blank-only candidates (safe hygiene).
    return page_count, blanks[:max_close]


def count_open_pages(port: int) -> int | None:
    """Return page-target count for a CDP port, or None when listing fails."""
    targets = _list_cdp_targets(port)
    if targets is None:
        return None
    return sum(1 for t in targets if t.target_type == "page")


async def _wait_for_port(port: int, *, attempts: int = 10, delay: float = 0.2) -> bool:
    """Poll a CDP port briefly until Chrome/socat is ready."""
    for attempt in range(attempts):
        if await probe_port(port):
            return True
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
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


async def _ensure_socat_forwarder(profile_path: str, port: int) -> int | None:
    """Start a socat forwarder 0.0.0.0:<port> → 127.0.0.1:<internal_port>.

    Chrome 144+ binds 127.0.0.1 only (ignores --remote-debugging-address=0.0.0.0),
    so the backend container (via host.containers.internal) can't connect. socat
    exposes the public ``port`` on 0.0.0.0 and forwards to Chrome's internal
    loopback port. Chrome and socat use *different* ports (0.0.0.0:port would
    conflict with 127.0.0.1:port since 0.0.0.0 subsumes loopback).

    No-op if 0.0.0.0:<port> is already listening (socat already up) or socat
    isn't installed. Returns the socat pid, or None when not started.
    """
    if _port_bound_inet(port):
        return None
    internal = _internal_cdp_port(port)
    if not await probe_port(internal, host="127.0.0.1"):
        return None
    bin_ = shutil.which("socat")
    if bin_ is None:
        logger.warning(
            "socat 未安装：Chrome 绑 127.0.0.1:%d，容器无法连接。装 socat 或换 Chrome 版本。",
            internal,
        )
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            bin_,
            f"TCP-LISTEN:{port},bind=0.0.0.0,reuseaddr,fork",
            f"TCP:127.0.0.1:{internal}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        logger.warning("socat forwarder 启动失败 (port %d): %s: %s", port, type(e).__name__, e)
        return None
    (Path(profile_path) / "socat.pid").write_text(str(proc.pid), encoding="utf-8")
    logger.info("socat forwarder up: 0.0.0.0:%d → 127.0.0.1:%d (pid %d)", port, internal, proc.pid)
    return proc.pid


def _port_bound_inet(port: int) -> bool:
    """Return True if any process is listening on 0.0.0.0:<port> (all interfaces).

    Used to decide whether socat forwarding is needed: Chrome 144 binds only
    127.0.0.1 even when --remote-debugging-address=0.0.0.0 is passed, so we check
    the actual socket table rather than HTTP-probing (0.0.0.0 as a connect target
    resolves to loopback and would lie).
    """
    import subprocess

    try:
        out = subprocess.run(
            ["ss", "-tlnH"], capture_output=True, text=True, timeout=2, check=False
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "LISTEN":
            local = parts[3]
            # local like "0.0.0.0:9224" or "[::]:9224"
            if local.endswith(f":{port}") and ("0.0.0.0" in local or "::" in local):
                return True
    return False


async def _stop_socat_forwarder(profile_path: str) -> None:
    """Terminate the socat forwarder for this profile (best-effort)."""
    pidfile = Path(profile_path) / "socat.pid"
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        os.kill(pid, signal.SIGTERM)
    with contextlib.suppress(FileNotFoundError, OSError):
        pidfile.unlink()


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


def _raw_cmdline_has_profile(raw: bytes, profile_path: str) -> bool:
    """Match an exact user-data-dir argument in normal or flattened procfs argv."""
    option = f"--user-data-dir={os.path.abspath(profile_path)}".encode()
    start = 0
    while True:
        index = raw.find(option, start)
        if index < 0:
            return False
        end = index + len(option)
        before_is_boundary = index == 0 or raw[index - 1] in b"\x00 \t\r\n"
        after_is_boundary = end == len(raw) or raw[end] in b"\x00 \t\r\n"
        if before_is_boundary and after_is_boundary:
            return True
        start = index + 1


def _pid_matches_profile(pid: int, profile_path: str) -> bool:
    """Return True when a pidfile PID is still Chrome for this profile."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return _raw_cmdline_has_profile(raw, profile_path)


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
            logger.warning("Failed to remove %s: %s: %s", p, type(e).__name__, e)
    if removed_any:
        logger.info("Cleared stale SingletonLock files in %s", profile_path)
    return removed_any


# ── Launch / stop ──


# Chrome 144+ binds 127.0.0.1 even with --remote-debugging-address=0.0.0.0, so the
# container can't reach it. We run a socat forwarder 0.0.0.0:<cdp_port> →
# 127.0.0.1:<cdp_port+INTERNAL_PORT_OFFSET>. Chrome must listen on a *different*
# port than socat (0.0.0.0:cdp_port and 127.0.0.1:cdp_port conflict — 0.0.0.0
# subsumes loopback), so Chrome takes cdp_port+OFFSET internally and socat
# exposes the public cdp_port.
_INTERNAL_PORT_OFFSET = 10000


def _internal_cdp_port(cdp_port: int) -> int:
    """Chrome's actual --remote-debugging-port (loopback only). socat maps the
    public cdp_port → this internal port."""
    return cdp_port + _INTERNAL_PORT_OFFSET


def _disk_cache_size_flag() -> str | None:
    """Return the configured Chrome disk-cache flag, or None for the default."""
    raw = os.environ.get("XHS_CHROME_DISK_CACHE_SIZE_MB", str(_DEFAULT_DISK_CACHE_SIZE_MB))
    try:
        size_mb = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid XHS_CHROME_DISK_CACHE_SIZE_MB=%r; using default %d MiB",
            raw,
            _DEFAULT_DISK_CACHE_SIZE_MB,
        )
        size_mb = _DEFAULT_DISK_CACHE_SIZE_MB
    if size_mb < 0:
        logger.warning(
            "Negative XHS_CHROME_DISK_CACHE_SIZE_MB=%d; using default %d MiB",
            size_mb,
            _DEFAULT_DISK_CACHE_SIZE_MB,
        )
        size_mb = _DEFAULT_DISK_CACHE_SIZE_MB
    if size_mb == 0:
        return None
    return f"--disk-cache-size={size_mb * 1024 * 1024}"


def _build_launch_cmd(chrome_bin: str, profile_path: str, port: int) -> list[str]:
    """Construct the Chrome command line for a per-account instance.

    Chrome listens on ``_internal_cdp_port(port)`` (127.0.0.1 only — Chrome 144
    ignores --remote-debugging-address). A socat forwarder exposes the public
    ``port`` on 0.0.0.0 for the backend container. See ``_ensure_socat_forwarder``.

    Always headed — headless Chrome is banned outright (XHS risk control blocks
    it: QR login fails with 300012 / "未找到登录二维码").

    Uses ``create_subprocess_exec`` (not a shell) — args are passed directly to
    execve, so no shell-injection surface even if profile_path/port ever came
    from untrusted input (they don't — both are DB-stored, operator-controlled).
    """
    cmd = [
        chrome_bin,
        f"--user-data-dir={profile_path}",
        f"--remote-debugging-port={_internal_cdp_port(port)}",
    ]
    cmd.extend(_DEFAULT_FLAGS)
    cache_size_flag = _disk_cache_size_flag()
    if cache_size_flag is not None:
        cmd.append(cache_size_flag)
    if os.environ.get("XHS_CHROME_CRASH_REPORTING", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # Crash reporting is opt-in for long-lived automation profiles; Chrome
        # otherwise starts crashpad helper processes per profile.
        cmd.append("--disable-crash-reporter")
    return cmd


async def ensure_chrome(
    account: AccountRow,
    *,
    chrome_bin: str | None = None,
) -> ChromeStatus:
    """Ensure one account Chrome is running under a cross-process profile lock."""
    if account.cdp_port <= 0 or not account.chrome_profile_path:
        return await _ensure_chrome_unlocked(account, chrome_bin=chrome_bin)
    try:
        async with _profile_launch_lock(account.chrome_profile_path):
            return await _ensure_chrome_unlocked(account, chrome_bin=chrome_bin)
    except TimeoutError as exc:
        return ChromeStatus(
            account_id=account.id,
            port=account.cdp_port,
            profile_path=account.chrome_profile_path,
            alive=False,
            action="failed",
            message=str(exc),
        )


async def _ensure_chrome_unlocked(
    account: AccountRow,
    *,
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

    # 1. Already reachable from the backend container?
    if await probe_port(port):
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=True,
            action="skipped",
            message="chrome already running on port",
        )

    # Chrome 144+ may be alive only on the internal loopback port while the
    # public socat forwarder is missing or died. Repair that before consulting
    # SingletonLock; otherwise a live profile lock would make us refuse the
    # launch without restoring container reachability.
    internal = _internal_cdp_port(port)
    if await probe_port(internal):
        await _ensure_socat_forwarder(profile_path, port)
        public_alive = await _wait_for_port(port)
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=public_alive,
            action="skipped" if public_alive else "failed",
            message=(
                "chrome internal port alive; public forwarder ready"
                if public_alive
                else "chrome internal port alive but public CDP port is not reachable"
            ),
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

    cmd = _build_launch_cmd(bin_, profile_path, port)
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

    # Give Chrome a moment to bind the DevTools port. Chrome 144 headed under
    # Xvfb can take ~2s to bind + answer /json/version — probe with retries
    # so socat (which needs Chrome up on 127.0.0.1) gets a ready target.
    # Chrome listens on _internal_cdp_port (loopback); socat exposes cdp_port.
    internal_alive = False
    for _ in range(10):
        await asyncio.sleep(0.5)
        internal_alive = await probe_port(internal)
        if internal_alive:
            break
    # Chrome 144+ binds 127.0.0.1 despite --remote-debugging-address=0.0.0.0;
    # socat forwards 0.0.0.0:cdp_port → 127.0.0.1:internal so the container can reach it.
    public_alive = False
    if internal_alive:
        await _ensure_socat_forwarder(profile_path, port)
        public_alive = await _wait_for_port(port)
    return ChromeStatus(
        account_id=account.id,
        port=port,
        profile_path=profile_path,
        alive=public_alive,
        action="launched" if public_alive else "failed",
        message=f"pid={proc.pid}, internal_port_up={internal_alive}, public_port_up={public_alive}",
    )


async def stop_chrome(account: AccountRow) -> ChromeStatus:
    """Stop one account Chrome while holding the profile lifecycle lock."""
    if not account.chrome_profile_path:
        return await _stop_chrome_unlocked(account)
    try:
        async with _profile_launch_lock(account.chrome_profile_path):
            return await _stop_chrome_unlocked(account)
    except TimeoutError as exc:
        return ChromeStatus(
            account_id=account.id,
            port=account.cdp_port,
            profile_path=account.chrome_profile_path,
            alive=True,
            action="failed",
            message=str(exc),
        )


async def _stop_chrome_unlocked(account: AccountRow) -> ChromeStatus:
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
        await _stop_socat_forwarder(profile_path)
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

    if not _pid_matches_profile(pid, profile_path):
        logger.warning("Refusing to signal pid %d: profile mismatch for %s", pid, profile_path)
        await _stop_socat_forwarder(profile_path)
        _clear_pidfile(profile_path)
        return ChromeStatus(
            account_id=account.id,
            port=port,
            profile_path=profile_path,
            alive=False,
            action="failed",
            message=f"pidfile PID {pid} does not belong to profile",
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
    await _stop_socat_forwarder(profile_path)
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


def _select_accounts(
    accounts: list[AccountRow], account_ids: Iterable[str] | None
) -> list[AccountRow]:
    """Filter accounts when explicit selectors were supplied."""
    selected = {value.strip() for value in (account_ids or ()) if value.strip()}
    if not selected:
        return accounts
    return [account for account in accounts if account.id in selected]


def _endpoint_port(endpoint: str) -> int | None:
    try:
        return int(endpoint.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        return None


def _has_active_cdp_connection(port: int) -> bool:
    """Return True when active or unverified; idle reap must fail closed."""
    import subprocess

    try:
        output = subprocess.run(
            ["ss", "-tnH"], capture_output=True, text=True, timeout=2, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    for line in output.splitlines():
        parts = line.split()
        if not parts or parts[0] not in {"ESTAB", "SYN-RECV"}:
            continue
        if any(_endpoint_port(endpoint) == port for endpoint in parts[-2:]):
            return True
    return False


def _iter_cache_dirs(profile_path: str) -> Iterator[Path]:
    """Yield only allowlisted cache directories beneath a Chrome profile."""
    root = Path(profile_path)
    if not root.is_dir():
        return
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for dirname in list(dirnames):
            candidate = current / dirname
            if candidate.is_symlink():
                dirnames.remove(dirname)
                continue
            if dirname in _SAFE_CACHE_DIR_NAMES:
                yield candidate
                dirnames.remove(dirname)


def _directory_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _safe_cache_bytes(profile_path: str) -> int:
    """Return bytes in the same allowlisted cache paths used by cleanup."""
    return sum(_directory_bytes(path) for path in _iter_cache_dirs(profile_path))


def _format_byte_count(byte_count: int) -> str:
    """Render a small, human-readable byte count for CLI status output."""
    for divisor, unit in ((1024**3, "GiB"), (1024**2, "MiB"), (1024, "KiB")):
        if byte_count >= divisor:
            return f"{byte_count / divisor:.1f}{unit}"
    return f"{byte_count}B"


def _memory_warning_threshold_bytes() -> int | None:
    """Return an optional process-tree RSS warning threshold from the environment."""
    raw = os.environ.get("XHS_CHROME_MEMORY_WARNING_MB", str(_DEFAULT_MEMORY_WARNING_MB))
    try:
        threshold_mb = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid XHS_CHROME_MEMORY_WARNING_MB=%r; disabling memory warning",
            raw,
        )
        return None
    if threshold_mb <= 0:
        if threshold_mb < 0:
            logger.warning(
                "Negative XHS_CHROME_MEMORY_WARNING_MB=%d; disabling memory warning",
                threshold_mb,
            )
        return None
    return threshold_mb * 1024 * 1024


def _iter_process_ids() -> Iterator[int]:
    """Yield process ids available from procfs without failing on races."""
    try:
        entries = Path("/proc").iterdir()
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and entry.name.isdecimal():
                yield int(entry.name)
        except OSError:
            continue


def _process_parent_and_rss_bytes(pid: int) -> tuple[int, int] | None:
    """Read PPid and VmRSS for one Linux process, returning None if unavailable."""
    try:
        lines = (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    parent_pid: int | None = None
    rss_bytes: int | None = None
    for line in lines:
        if line.startswith("PPid:"):
            try:
                parent_pid = int(line.split()[1])
            except (IndexError, ValueError):
                return None
        elif line.startswith("VmRSS:"):
            try:
                rss_bytes = int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    if parent_pid is None or rss_bytes is None:
        return None
    return parent_pid, rss_bytes


def _process_stats_snapshot() -> dict[int, tuple[int, int]]:
    """Take one best-effort procfs snapshot for all later tree lookups."""
    return {
        pid: stats
        for pid in _iter_process_ids()
        if (stats := _process_parent_and_rss_bytes(pid)) is not None
    }


def _process_tree_rss_bytes(
    root_pid: int, process_snapshot: dict[int, tuple[int, int]] | None = None
) -> tuple[int, int] | None:
    """Return process count and summed RSS bytes for a procfs process tree."""
    processes = process_snapshot if process_snapshot is not None else _process_stats_snapshot()
    if root_pid not in processes:
        return None
    descendants = {root_pid}
    while True:
        children = {pid for pid, (parent_pid, _) in processes.items() if parent_pid in descendants}
        next_descendants = descendants | children
        if next_descendants == descendants:
            break
        descendants = next_descendants
    return len(descendants), sum(processes[pid][1] for pid in descendants)


def _profile_chrome_resources(
    profile_path: str,
    *,
    process_snapshot: dict[int, tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    """Report only a live pidfile Chrome tree that still belongs to this profile."""
    pid = _read_pidfile(profile_path)
    if pid is None or not _pid_alive(pid) or not _pid_matches_profile(pid, profile_path):
        return None
    return _process_tree_rss_bytes(pid, process_snapshot)


def _profile_chrome_resources_for_profiles(
    profile_paths: Iterable[str],
) -> dict[str, tuple[int, int] | None]:
    """Read procfs once, then resolve resource ownership for each profile."""
    process_snapshot = _process_stats_snapshot()
    return {
        profile_path: _profile_chrome_resources(profile_path, process_snapshot=process_snapshot)
        for profile_path in profile_paths
    }


def _profile_is_live(profile_path: str) -> bool:
    """Return True if a matching pidfile process or live SingletonLock exists."""
    pid = _read_pidfile(profile_path)
    if pid is not None and _pid_alive(pid) and _pid_matches_profile(pid, profile_path):
        return True
    lock = Path(profile_path) / "SingletonLock"
    if not lock.is_symlink() and not lock.exists():
        return False
    lock_pid = _singleton_lock_pid(profile_path)
    return lock_pid is None or _pid_alive(lock_pid)


def cleanup_profile_cache(profile_path: str, *, apply: bool = False) -> tuple[int, int]:
    """Report or remove allowlisted cache bytes; never touch login storage."""
    if _profile_is_live(profile_path):
        raise RuntimeError("profile Chrome is running; stop it before cache cleanup")
    cache_dirs = list(_iter_cache_dirs(profile_path) or ())
    before = sum(_directory_bytes(path) for path in cache_dirs)
    if not apply:
        return before, 0
    for cache_dir in cache_dirs:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(cache_dir)
    after = sum(_directory_bytes(path) for path in cache_dirs if path.exists())
    return before, max(0, before - after)


async def reap_idle(
    accounts: list[AccountRow],
    idle_seconds: float,
    *,
    account_ids: Iterable[str] | None = None,
) -> list[ChromeStatus]:
    """Stop old profiles only when no active CDP client is connected."""
    if not math.isfinite(idle_seconds) or idle_seconds <= 0:
        raise ValueError("idle_seconds must be a finite positive number")
    now = time.time()
    targets = [
        account
        for account in _select_accounts(accounts, account_ids)
        if account.chrome_profile_path and account.cdp_port > 0
    ]

    async def _reap(account: AccountRow) -> ChromeStatus:
        pidfile = Path(account.chrome_profile_path) / "chrome.pid"
        pid = _read_pidfile(account.chrome_profile_path)
        if pid is None or not _pid_alive(pid):
            return ChromeStatus(
                account.id,
                account.cdp_port,
                account.chrome_profile_path,
                False,
                "skipped",
                "chrome already down",
            )
        if _has_active_cdp_connection(account.cdp_port):
            return ChromeStatus(
                account.id,
                account.cdp_port,
                account.chrome_profile_path,
                True,
                "skipped",
                "active or unverified CDP connection",
            )
        try:
            age = now - pidfile.stat().st_mtime
        except OSError as exc:
            return ChromeStatus(
                account.id,
                account.cdp_port,
                account.chrome_profile_path,
                True,
                "failed",
                f"cannot inspect pidfile age: {exc}",
            )
        if age < idle_seconds:
            return ChromeStatus(
                account.id,
                account.cdp_port,
                account.chrome_profile_path,
                True,
                "skipped",
                f"idle for {age:.0f}s (< {idle_seconds:.0f}s)",
            )
        return await stop_chrome(account)

    return await asyncio.gather(*(_reap(account) for account in targets))


async def cleanup_all(
    accounts: list[AccountRow],
    *,
    apply: bool = False,
    account_ids: Iterable[str] | None = None,
) -> list[ProfileCleanupStatus]:
    """Dry-run or apply safe cache cleanup for selected profiles."""
    targets = [
        account
        for account in _select_accounts(accounts, account_ids)
        if account.chrome_profile_path
    ]

    async def _cleanup(account: AccountRow) -> ProfileCleanupStatus:
        if account.cdp_port > 0 and await probe_port(account.cdp_port):
            return ProfileCleanupStatus(
                account.id,
                account.chrome_profile_path,
                0,
                0,
                "skipped",
                "public CDP endpoint is live",
            )
        try:
            async with _profile_launch_lock(account.chrome_profile_path):
                cache_bytes, removed_bytes = cleanup_profile_cache(
                    account.chrome_profile_path, apply=apply
                )
        except (OSError, RuntimeError) as exc:
            return ProfileCleanupStatus(
                account.id, account.chrome_profile_path, 0, 0, "failed", str(exc)
            )
        return ProfileCleanupStatus(
            account.id,
            account.chrome_profile_path,
            cache_bytes,
            removed_bytes,
            "cleaned" if apply else "dry_run",
            "cache removed" if apply else "cache eligible for cleanup",
        )

    return await asyncio.gather(*(_cleanup(account) for account in targets))


async def prune_blank_pages_all(
    accounts: list[AccountRow],
    *,
    apply: bool = False,
    account_ids: Iterable[str] | None = None,
) -> list[PageCleanupStatus]:
    """Dry-run or close one safe blank page per selected profile.

    An apply is fail-closed: it requires no active CDP client, takes the
    profile lock, re-lists targets, and retains at least one page target.
    """
    selected_ids = tuple(value for value in (account_ids or ()) if value.strip())
    if apply and not selected_ids:
        raise ValueError("page cleanup apply requires at least one account id")

    targets = [
        account
        for account in _select_accounts(accounts, account_ids)
        if account.chrome_profile_path and account.cdp_port > 0
    ]

    async def _prune(account: AccountRow) -> PageCleanupStatus:
        if not await probe_port(account.cdp_port):
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                0,
                0,
                0,
                "skipped",
                "public CDP endpoint is down",
            )
        if _has_active_cdp_connection(account.cdp_port):
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                0,
                0,
                0,
                "skipped",
                "active or unverified CDP connection",
            )
        cdp_targets = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
        if cdp_targets is None:
            return PageCleanupStatus(
                account.id, account.cdp_port, 0, 0, 0, "failed", "cannot list CDP targets"
            )
        page_count, candidates = _blank_page_cleanup_candidates(cdp_targets)
        if not candidates:
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                page_count,
                0,
                0,
                "skipped",
                "no safe blank page candidates",
            )
        if not apply:
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                page_count,
                len(candidates),
                0,
                "dry_run",
                "safe blank page eligible for cleanup",
            )
        try:
            async with _profile_launch_lock(account.chrome_profile_path):
                if not await probe_port(account.cdp_port):
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "skipped",
                        "public CDP endpoint went down before apply",
                    )
                if _has_active_cdp_connection(account.cdp_port):
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "skipped",
                        "active or unverified CDP connection",
                    )
                verified_targets = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
                if verified_targets is None:
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "failed",
                        "cannot recheck CDP targets",
                    )
                page_count, candidates = _blank_page_cleanup_candidates(verified_targets)
                if not candidates:
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        page_count,
                        0,
                        0,
                        "skipped",
                        "no safe blank page candidates after recheck",
                    )
                if not await asyncio.to_thread(
                    _close_cdp_target, account.cdp_port, candidates[0].target_id
                ):
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        page_count,
                        len(candidates),
                        0,
                        "failed",
                        "CDP refused safe blank page close",
                    )
                post_close_targets = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
                if post_close_targets is None:
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        page_count,
                        len(candidates),
                        1,
                        "cleaned",
                        "closed one safe blank page; post-close verification unavailable",
                    )
                remaining_pages, remaining_candidates = _blank_page_cleanup_candidates(
                    post_close_targets
                )
                return PageCleanupStatus(
                    account.id,
                    account.cdp_port,
                    remaining_pages,
                    len(remaining_candidates),
                    1,
                    "cleaned",
                    "closed one safe blank page",
                )
        except (OSError, TimeoutError) as exc:
            return PageCleanupStatus(account.id, account.cdp_port, 0, 0, 0, "failed", str(exc))

    return await asyncio.gather(*(_prune(account) for account in targets))


async def hygiene_browser_pages_all(
    accounts: list[AccountRow],
    *,
    apply: bool = False,
    account_ids: Iterable[str] | None = None,
    max_pages: int = 6,
    max_close: int = 3,
) -> list[PageCleanupStatus]:
    """Close excess blank / duplicate Creator Center tabs (anti-risk hygiene).

    Unlike ``prune_blank_pages_all`` (one blank only), this pass may close
    multiple safe targets per profile — blanks first, then extra creator tabs —
    while still retaining at least one page and refusing to run under an active
    CDP client attachment.
    """
    selected_ids = tuple(value for value in (account_ids or ()) if value.strip())
    if apply and not selected_ids:
        raise ValueError("page hygiene apply requires at least one account id")

    targets = [
        account
        for account in _select_accounts(accounts, account_ids)
        if account.chrome_profile_path and account.cdp_port > 0
    ]
    close_limit = max(1, int(max_close or 1))
    page_cap = max(1, int(max_pages or 1))

    async def _hygiene(account: AccountRow) -> PageCleanupStatus:
        if not await probe_port(account.cdp_port):
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                0,
                0,
                0,
                "skipped",
                "public CDP endpoint is down",
            )
        if _has_active_cdp_connection(account.cdp_port):
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                0,
                0,
                0,
                "skipped",
                "active or unverified CDP connection",
            )
        cdp_targets = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
        if cdp_targets is None:
            return PageCleanupStatus(
                account.id, account.cdp_port, 0, 0, 0, "failed", "cannot list CDP targets"
            )
        page_count, candidates = _hygiene_page_cleanup_candidates(cdp_targets, max_pages=page_cap)
        candidates = candidates[:close_limit]
        if not candidates:
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                page_count,
                0,
                0,
                "skipped",
                "no excess page candidates",
            )
        if not apply:
            return PageCleanupStatus(
                account.id,
                account.cdp_port,
                page_count,
                len(candidates),
                0,
                "dry_run",
                "excess pages eligible for hygiene",
            )
        try:
            async with _profile_launch_lock(account.chrome_profile_path):
                if not await probe_port(account.cdp_port):
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "skipped",
                        "public CDP endpoint went down before apply",
                    )
                if _has_active_cdp_connection(account.cdp_port):
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "skipped",
                        "active or unverified CDP connection",
                    )
                verified = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
                if verified is None:
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        0,
                        0,
                        0,
                        "failed",
                        "cannot recheck CDP targets",
                    )
                page_count, candidates = _hygiene_page_cleanup_candidates(
                    verified, max_pages=page_cap
                )
                candidates = candidates[:close_limit]
                if not candidates:
                    return PageCleanupStatus(
                        account.id,
                        account.cdp_port,
                        page_count,
                        0,
                        0,
                        "skipped",
                        "no excess page candidates after recheck",
                    )
                closed = 0
                for candidate in candidates:
                    if await asyncio.to_thread(
                        _close_cdp_target, account.cdp_port, candidate.target_id
                    ):
                        closed += 1
                post = await asyncio.to_thread(_list_cdp_targets, account.cdp_port)
                remaining = (
                    sum(1 for t in post if t.target_type == "page")
                    if post is not None
                    else page_count
                )
                return PageCleanupStatus(
                    account.id,
                    account.cdp_port,
                    remaining,
                    len(candidates),
                    closed,
                    "cleaned" if closed else "failed",
                    f"closed {closed} excess page(s)" if closed else "CDP refused page close",
                )
        except (OSError, TimeoutError) as exc:
            return PageCleanupStatus(account.id, account.cdp_port, 0, 0, 0, "failed", str(exc))

    return await asyncio.gather(*(_hygiene(account) for account in targets))


# ── Bulk helpers (used by the bash wrapper) ──


async def ensure_all(
    accounts: list[AccountRow],
    *,
    chrome_bin: str | None = None,
    account_ids: Iterable[str] | None = None,
) -> list[ChromeStatus]:
    """Ensure Chrome is up for every account that has a port binding.

    Accounts without ``cdp_port``/``chrome_profile_path`` are skipped (they
    fall back to the global CDP endpoint at publish time). Run concurrently —
    each Chrome launches independently.
    """
    targets = [
        a
        for a in _select_accounts(accounts, account_ids)
        if a.is_active and a.cdp_port > 0 and a.chrome_profile_path
    ]
    if not targets:
        return []
    return await asyncio.gather(*(ensure_chrome(a, chrome_bin=chrome_bin) for a in targets))


async def stop_all(
    accounts: list[AccountRow],
    *,
    account_ids: Iterable[str] | None = None,
) -> list[ChromeStatus]:
    """Stop Chrome for every account that has a profile binding."""
    targets = [a for a in _select_accounts(accounts, account_ids) if a.chrome_profile_path]
    if not targets:
        return []
    return await asyncio.gather(*(stop_chrome(a) for a in targets))


async def status_all(
    accounts: list[AccountRow],
    *,
    account_ids: Iterable[str] | None = None,
) -> list[ChromeStatus]:
    """Probe each account port and read profile resources without mutation."""
    targets = [
        a
        for a in _select_accounts(accounts, account_ids)
        if a.chrome_profile_path and a.cdp_port > 0
    ]
    if not targets:
        return []

    memory_warning_bytes = _memory_warning_threshold_bytes()
    chrome_resources_task = asyncio.create_task(
        asyncio.to_thread(
            _profile_chrome_resources_for_profiles,
            [a.chrome_profile_path for a in targets],
        )
    )

    async def _probe(a: AccountRow) -> ChromeStatus:
        alive, cache_bytes = await asyncio.gather(
            probe_port(a.cdp_port),
            asyncio.to_thread(_safe_cache_bytes, a.chrome_profile_path),
        )
        chrome_resources = (await chrome_resources_task)[a.chrome_profile_path]
        status_text = "alive" if alive else "down"
        message_parts = [status_text, f"safe_cache={_format_byte_count(cache_bytes)}"]
        if chrome_resources is None:
            message_parts.append("chrome_resources=unknown")
        else:
            process_count, rss_bytes = chrome_resources
            message_parts.extend(
                (
                    f"chrome_processes={process_count}",
                    f"chrome_rss={_format_byte_count(rss_bytes)}",
                )
            )
            if memory_warning_bytes is not None and rss_bytes >= memory_warning_bytes:
                message_parts.append("memory=warning")
        return ChromeStatus(
            account_id=a.id,
            port=a.cdp_port,
            profile_path=a.chrome_profile_path,
            alive=alive,
            action="skipped",
            message="; ".join(message_parts),
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
    "PageCleanupStatus",
    "ProfileCleanupStatus",
    "cleanup_all",
    "cleanup_profile_cache",
    "format_cleanup_table",
    "format_page_cleanup_table",
    "reap_idle",
    "clear_stale_lock",
    "ensure_all",
    "ensure_chrome",
    "find_chrome_binary",
    "format_status_table",
    "count_open_pages",
    "hygiene_browser_pages_all",
    "probe_port",
    "prune_blank_pages_all",
    "status_all",
    "stop_all",
    "stop_chrome",
]


# ── CLI entry (called by scripts/chrome-profiles.sh) ──
#
# ``python3 -m backend.services.chrome_launcher <start|status|stop|reap|cleanup|
# prune-pages>`` loads the
# accounts list from the DB (via backend.db.accounts.list_accounts) and runs the
# matching bulk op. The bash wrapper is intentionally thin — it just forwards
# the subcommand so operators don't need to remember the python invocation.
#
# DB connectivity: this runs on the host (Chrome lives on the host), but the DB
# is in the postgres-xhs container. POSTGRES_URI must be reachable from the host
# (deploy.sh publishes 5432 on the host, so localhost:5432 works). If the pool
# isn't ready, every subcommand degrades gracefully — status reports "no
# accounts", start/stop report nothing to do.


def format_cleanup_table(statuses: list[ProfileCleanupStatus]) -> str:
    """Render cache cleanup results without exposing profile contents."""
    if not statuses:
        return "(no accounts with chrome profile bindings)"
    lines = ["ACCOUNT PROFILE ACTION CACHE_BYTES REMOVED MESSAGE"]
    for status in statuses:
        lines.append(
            f"{status.account_id} {status.profile_path} {status.action} {status.cache_bytes} "
            f"{status.removed_bytes} {status.message}"
        )
    return "\n".join(lines)


def format_page_cleanup_table(statuses: list[PageCleanupStatus]) -> str:
    """Render blank-page cleanup results without exposing page URLs or titles."""
    if not statuses:
        return "(no accounts with chrome profile bindings)"
    lines = ["ACCOUNT PORT ACTION PAGES CANDIDATES CLOSED MESSAGE"]
    for status in statuses:
        lines.append(
            f"{status.account_id} {status.port} {status.action} {status.page_count} "
            f"{status.candidate_count} {status.closed_count} {status.message}"
        )
    return "\n".join(lines)


def _configured_idle_seconds(value: float | None) -> float:
    """Resolve and validate the idle threshold for maintenance."""
    raw = (
        value
        if value is not None
        else os.environ.get("XHS_CHROME_IDLE_TIMEOUT_SECONDS", str(_DEFAULT_IDLE_TIMEOUT_SECONDS))
    )
    try:
        seconds = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("XHS_CHROME_IDLE_TIMEOUT_SECONDS must be numeric") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("idle timeout must be a finite positive number")
    return seconds


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
            logger.warning("chrome-launcher CLI: DB pool init failed: %s: %s", type(e).__name__, e)
            return []

    if not is_pool_ready():
        return []
    try:
        from backend.db.accounts import list_accounts

        return await list_accounts()
    except Exception as e:  # noqa: BLE001 — degrade, don't crash the CLI
        logger.warning("chrome-launcher CLI: list_accounts failed: %s: %s", type(e).__name__, e)
        return []


async def _cli(
    subcommand: str,
    *,
    account_ids: Iterable[str] | None = None,
    idle_seconds: float | None = None,
    apply_cleanup: bool = False,
) -> int:
    """Run the requested bulk op against all accounts. Returns exit code."""
    accounts = await _load_accounts()
    if subcommand == "start":
        statuses = await ensure_all(accounts, account_ids=account_ids)
    elif subcommand == "status":
        statuses = await status_all(accounts, account_ids=account_ids)
    elif subcommand == "stop":
        statuses = await stop_all(accounts, account_ids=account_ids)
    elif subcommand == "reap":
        try:
            statuses = await reap_idle(
                accounts, _configured_idle_seconds(idle_seconds), account_ids=account_ids
            )
        except ValueError as exc:
            print(f"invalid idle timeout: {exc}")
            return 2
    elif subcommand == "cleanup":
        cleanup_statuses = await cleanup_all(accounts, apply=apply_cleanup, account_ids=account_ids)
        print(format_cleanup_table(cleanup_statuses))
        return 1 if any(s.action == "failed" for s in cleanup_statuses) else 0

    elif subcommand == "prune-pages":
        selected_ids = tuple(value for value in (account_ids or ()) if value.strip())
        if apply_cleanup and not selected_ids:
            print("prune-pages --apply requires at least one --account-id")
            return 2
        page_statuses = await prune_blank_pages_all(
            accounts, apply=apply_cleanup, account_ids=selected_ids
        )
        print(format_page_cleanup_table(page_statuses))
        return 1 if any(status.action == "failed" for status in page_statuses) else 0

    else:  # pragma: no cover — argparse choices() rejects this
        print(f"unknown subcommand: {subcommand} (use start|status|stop|reap|cleanup|prune-pages)")
        return 2

    print(format_status_table(statuses))
    # Exit non-zero if any account failed to launch/stop — operator should see it.
    failed = [s for s in statuses if s.action == "failed"]
    return 1 if failed else 0


def main() -> None:
    """CLI entry for the start/status/stop/reap/cleanup/prune-pages commands."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="chrome-launcher",
        description="Manage per-account always-on Chrome instances (CDP multi-profile).",
    )
    parser.add_argument(
        "subcommand",
        choices=("start", "status", "stop", "reap", "cleanup", "prune-pages"),
        help=(
            "start=launch, status=probe, stop=stop, reap=idle cleanup, "
            "cleanup=cache cleanup, prune-pages=blank page cleanup"
        ),
    )
    parser.add_argument(
        "--account-id",
        action="append",
        dest="account_ids",
        default=[],
        help="limit the operation to one account; repeat for multiple accounts",
    )
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=None,
        help="idle threshold for reap (default: XHS_CHROME_IDLE_TIMEOUT_SECONDS or 1800)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply cleanup; without it cleanup is a dry run",
    )

    args = parser.parse_args()

    import asyncio

    from backend.db.pool import close_pool

    try:
        code = asyncio.run(
            _cli(
                args.subcommand,
                account_ids=args.account_ids,
                idle_seconds=args.idle_seconds,
                apply_cleanup=args.apply,
            )
        )
    finally:
        with contextlib.suppress(Exception):  # noqa: BLE001 — best-effort cleanup on the way out
            asyncio.run(close_pool())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
