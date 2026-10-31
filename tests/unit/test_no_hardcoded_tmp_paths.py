"""No backend module may hard-code a POSIX temp path.

``/tmp/...`` looks portable on Linux and in containers, which is why two writers
used it: the image upload dir (``backend/api/routes/_wf_application.py``) and the
generated-cover dir (``backend/agents/publisher.py``).  On Windows the same string
resolves to the current drive's root -- ``\\tmp\\...`` -- which is outside the user
profile and, in a sandboxed or locked-down process, simply not writable.  The
failure showed up as the only deterministic red in a full local suite:
``Permission denied: '\\tmp\\xhs_images\\...'``.

The portable form is ``tempfile.gettempdir()``: on Linux/containers it returns
``/tmp`` (so behaviour is unchanged), on Windows the user's temp dir, and tests or
deployments can still point ``TMPDIR``/``TEMP`` elsewhere -- standard behaviour,
not a bespoke knob.

The check is deliberately an AST scan over *string constants*, not a grep:
comments and docstrings are allowed to mention ``/tmp`` (this module does), and a
docstring is not a write.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"


def _is_posix_temp_path(value: str) -> bool:
    """Whether a string constant names an absolute POSIX temp path."""
    return value == "/tmp" or value.startswith("/tmp/")


def _hardcoded_tmp(dir_path: Path) -> list[str]:
    """Files under *dir_path* that define a string constant naming a POSIX temp path."""
    offenders: list[str] = []
    for path in sorted(dir_path.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _is_posix_temp_path(node.value)
            ):
                offenders.append(f"{path.relative_to(dir_path.parent)}:{node.lineno}")
                break
    return offenders


def test_no_backend_module_hardcodes_a_posix_temp_path() -> None:
    offenders = _hardcoded_tmp(_BACKEND)
    assert offenders == [], (
        "hard-coded /tmp paths are not portable (Windows resolves them to \\tmp); "
        f"use tempfile.gettempdir(): {offenders}"
    )


def test_the_temp_path_predicate_discriminates() -> None:
    """Positive/negative control for the classifier the scan above relies on."""
    assert _is_posix_temp_path("/tmp")
    assert _is_posix_temp_path("/tmp/xhs_images")
    assert not _is_posix_temp_path("/tmpfiles")
    assert not _is_posix_temp_path("tmp/x")
    assert not _is_posix_temp_path("C:/tmp/x")
