"""Guard: environment variables documented in `.env.example` must reach the container.

`scripts/deploy.sh` does not mount `.env` into the container (it is excluded by
`.dockerignore`; the image only COPYs source dirs), so the container process env
is exactly the explicit `podman run -e KEY=...` list. That makes any documented
knob missing from that list silently inert in production — the exact reason the
E2 `XHS_HARNESS_POLICY` knob first shipped unusable.

These tests keep the three surfaces aligned:
  * template -> deploy: every active `.env.example` key is passed through, or is
    explicitly host-only (the optional `.[memory-hy]` extra is not in the image).
  * code -> deploy: every key read from `os.environ` by `backend/` that is also
    documented in the template is passed through, so uncommenting a template
    knob cannot quietly do nothing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / ".env.example"
DEPLOY = ROOT / "scripts" / "deploy.sh"
BACKEND = ROOT / "backend"

# Host/dev only: the deploy image installs `.[browser]`, not `.[memory-hy]`, so
# the SDK is absent inside the container and passing these would only produce a
# loud "SDK not installed" error. Documented as host/dev-only in the template.
HOST_ONLY_PREFIXES = ("HYMEMORY_",)
# Documented legacy compatibility knob that no longer has a reader in code.
HOST_ONLY_KEYS = {"CREATOR_STATS_MAX_BODY_VISITS"}

KEY_RE = re.compile(r"^(#\s*)?([A-Z][A-Z0-9_]+)=")


def _template_keys() -> tuple[set[str], set[str]]:
    active: set[str] = set()
    commented: set[str] = set()
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        match = KEY_RE.match(line)
        if match:
            (commented if match.group(1) else active).add(match.group(2))
    return active, commented


def _deploy_keys() -> set[str]:
    return set(re.findall(r"-e\s+([A-Z][A-Z0-9_]+)=", DEPLOY.read_text(encoding="utf-8")))


def _backend_env_reads() -> set[str]:
    reads: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                func = node.func
                func_name = (
                    func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                )
                if func_name in {"get", "getenv"} and isinstance(node.args[0].value, str):
                    name = node.args[0].value
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                name = node.slice.value
            if name and re.match(r"^[A-Z][A-Z0-9_]+$", name):
                reads.add(name)
    return reads


def _is_host_only(key: str) -> bool:
    return key in HOST_ONLY_KEYS or key.startswith(HOST_ONLY_PREFIXES)


def test_active_template_keys_are_passed_to_container() -> None:
    active, _ = _template_keys()
    deploy = _deploy_keys()
    missing = sorted(k for k in active - deploy if not _is_host_only(k))
    assert not missing, (
        "`.env.example` documents keys that deploy.sh never passes into the container "
        f"(they would be silently inert): {missing}"
    )


def test_documented_knobs_read_by_backend_are_passed_to_container() -> None:
    active, commented = _template_keys()
    documented = active | commented
    deploy = _deploy_keys()
    reads = _backend_env_reads()
    missing = sorted(k for k in (documented & reads) - deploy if not _is_host_only(k))
    assert not missing, (
        "backend reads these documented env keys, but deploy.sh does not pass them "
        f"(uncommenting them in .env would do nothing in production): {missing}"
    )


def test_host_only_allowlist_stays_documented() -> None:
    """Every exempted key must still exist in the template, so the allowlist can rot visibly."""
    active, commented = _template_keys()
    documented = active | commented
    stale = sorted(k for k in HOST_ONLY_KEYS if k not in documented)
    assert not stale, f"host-only allowlist references undocumented keys: {stale}"
    assert any(k.startswith(HOST_ONLY_PREFIXES) for k in documented), (
        "HYMEMORY_* entries disappeared from .env.example; drop the allowlist if intentional"
    )
