"""One rule for every ``path:line`` we publish: it has to point at something.

``docs/execution-plane.md`` §8 states the rule -- "new references are always written
as full repo-relative paths" -- and used to enforce it for that one document.  This
module is the same rule for the whole corpus we own, plus the thing a corpus-wide
rule needs and a single-document rule does not: a way to tell a *citation* from a
string that merely has the same shape.

The shapes collide.  ``_wf_actions.py:101`` and ``localhost:8000`` are both
backticked ``[A-Za-z0-9_./-]+:<digits>``.  The first is a citation written in the
wrong form (that file exists, at ``backend/api/routes/_wf_actions.py``); the second
is a host and a port.  No property of the *text* separates them, so the
discriminator is the tree:

    a slash-less token is a citation when the tree attests its name, or its kind

"Attests its name" = some file in the tree is called ``_wf_actions.py``.
"Attests its kind" = some file in the tree ends in ``.py``.  Both are *derived*, so
the rule grows with the repository instead of with a list somebody has to remember
to extend -- an extension whitelist is exactly the mistake the L1 scanner in
``docs/tool-runtime.md`` records, because ``Dockerfile:81`` is a citation and does
not have one.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

# Never part of "the tree we own": version control, virtualenvs, caches, build
# output.  Everything else whose name starts with a dot is skipped as well -- that
# is the corpus rule too, see ``documents``.
_NOT_OURS = frozenset({".git", ".venv", "node_modules", "__pycache__", "dist", "build"})

# The two shapes a cited line number takes.  They are disjoint: the first needs at
# least one path character before the colon, the second has none.  The first also
# accepts a range (``path:357-359``), because prose uses ranges and a pattern that
# cannot see one would silently skip both ends.
_PATH_LINE = re.compile(r"`([A-Za-z0-9_./-]+):(\d+)(?:-(\d+))?`")
_BARE_LINE = re.compile(r"`:(\d+)`")

# A suffix that could name a file *type*: alphabetic and short.  This is a shape
# rule, not a list -- it is what keeps ``127.0.0.1:8000``'s ``.1`` out without
# anyone having to enumerate the extensions that are in.
_SUFFIX = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,9}\Z")


def _walk(root: Path) -> list[str]:
    """Every path under *root* that is ours, sorted, repo-relative posix form."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in _NOT_OURS and not name.startswith(".")
        )
        here = Path(dirpath).relative_to(root)
        found.extend((here / name).as_posix() for name in filenames)
    return sorted(found)


@lru_cache(maxsize=16)
def _tree(root: Path) -> tuple[tuple[str, ...], frozenset[str], frozenset[str]]:
    """``(every path, every name, every final suffix)`` for *root*.

    Only the *names* are cached, never the contents: the mutation harness rewrites
    file bodies while it runs, and a cached line count would answer for the wrong
    bytes.
    """
    files = _walk(root)
    names = frozenset(PurePosixPath(path).name for path in files)
    suffixes = frozenset(
        suffix for suffix in (PurePosixPath(path).suffix for path in files) if _SUFFIX.match(suffix)
    )
    return tuple(files), names, suffixes


def documents(root: Path) -> list[str]:
    """Every markdown document we own, repo-relative and sorted.

    The corpus is defined by a **shape**, not by a list of directories to skip: a
    path component starting with a dot takes the file out.  So ``.trellis/``
    (tickets are a historical record -- a citation inside one is not maintained),
    ``.claude/`` and ``.cursor/`` (vendored skill documentation) are out, while
    ``docs/``, the repository root and ``frontend/`` are in.
    """
    return [
        path
        for path in _tree(root)[0]
        if path.endswith(".md") and not PurePosixPath(path).name.startswith(".")
    ]


def _how(root: Path, token: str) -> str:
    """How *token* names the tree.

    ``"path"`` -- it *is* a file, repo-relative (``backend/api/routes/_runner.py``,
    or ``Dockerfile``);
    ``"name"`` -- no such path, but a file somewhere is called that;
    ``"kind"`` -- no such name, but files of that type exist (a typo'd basename);
    ``"none"`` -- the tree attests neither, so this is not a citation at all.

    A slash settles it without asking the tree, and it has to come before the name
    test: ``backend/api/old/_runner.py`` names no file, but ``_runner.py`` does, so
    the name branch would answer "bare basename, did you mean ..." to a token that
    was never bare.  Its real complaint is "no such file", which is what a drifted
    full path deserves.
    """
    if (root / token).is_file():
        return "path"
    if "/" in token:
        return "path"
    _, names, suffixes = _tree(root)
    if PurePosixPath(token).name in names:
        return "name"
    if PurePosixPath(token).suffix in suffixes:
        return "kind"
    return "none"


def _same_name(root: Path, token: str) -> tuple[str, ...]:
    """Every file whose name is *token*'s name.  Two of the 94 ambiguous names are
    load-bearing here (``__init__.py``, ``conftest.py``), so this can be plural."""
    name = PurePosixPath(token).name
    return tuple(path for path in _tree(root)[0] if PurePosixPath(path).name == name)


def _size(root: Path, relative: str) -> int | None:
    target = root / relative
    if not target.is_file():
        return None
    return len(target.read_text(encoding="utf-8", errors="replace").splitlines())


def _citations(line: str) -> list[tuple[int, str, re.Match[str]]]:
    """Every citation on one line, **in the order it appears**.

    Order is the whole semantics of a bare ``:N``: it means the path that precedes
    it *in the line*.  A line can cite two files -- §0 of the execution-plane doc
    does, ``..._wf_application.py:271`` ... ``:275`` ... ``_wf_models.py:31`` -- so
    collecting every path first and every bare number second attributes the bare one
    to the wrong file.  (This caught exactly that in its own first version: it
    reported ``:275`` as past the end of a 195-line file that the line only mentions
    *after* it.)
    """
    items = [(match.start(), "path", match) for match in _PATH_LINE.finditer(line)]
    items += [(match.start(), "bare", match) for match in _BARE_LINE.finditer(line)]
    return sorted(items, key=lambda item: item[0])


def _cited(text: str, root: Path) -> tuple[list[tuple[str, str, str | None]], list[int]]:
    """Every citation in *text*: ``path``/start/end triples, and bare lines.

    Tokens the tree does not attest at all are **not** citations and are not
    counted.  The port in ``localhost:8000`` is not a line number that can rot, and
    counting it would inflate the one number that says how much prose cites the
    tree.

    A range counts as one citation here and as two checked ends in :func:`_rot` --
    the count answers "how much prose cites the tree", the check answers "does it
    still point there".
    """
    triples = [found for found in _PATH_LINE.findall(text) if _how(root, found[0]) != "none"]
    return triples, [int(number) for number in _BARE_LINE.findall(text)]


def _resolved_by_name(root: Path, token: str) -> str | None:
    """The one file with *token*'s name, or ``None`` when none or several have it."""
    where = _same_name(root, token)
    return where[0] if len(where) == 1 else None


def _rot(text: str, root: Path) -> list[str]:
    """Every way a cited line number can fail to resolve, as readable complaints.

    Forms, all of them real: a path that is not there, a line past the end, a bare
    reference attributed past the end, a bare reference with no path before it to
    attribute it to, a range whose ends disagree with the file, and -- the one this
    corpus forced -- a citation written as a bare basename, which is reported with
    the path that would resolve it.
    """
    problems: list[str] = []
    section = ""
    last: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            section, last = line.strip(), None
        for _, kind, match in _citations(line):
            if kind == "bare":
                bare = int(match.group(1))
                if last is None:
                    problems.append(f":{number} :{bare} -> bare, no path before it in {section!r}")
                    continue
                target = last if _how(root, last) == "path" else _resolved_by_name(root, last)
                size = _size(root, target) if target is not None else None
                if size is not None and not 0 < bare <= size:
                    problems.append(f":{number} :{bare} -> {last} past the end ({size} lines)")
                continue

            token, start, end = match.group(1), int(match.group(2)), match.group(3)
            how = _how(root, token)
            if how == "none":
                # Not a citation: a host and a port, an image tag, a word.  It is
                # deliberately *not* remembered as the attribution target either --
                # ``localhost:8000`` must not adopt the ``:12`` that follows it.
                continue
            last = token
            target = token
            if how == "name":
                target = _resolved_by_name(root, token)
                if target is None:
                    where = _same_name(root, token)
                    problems.append(
                        f":{number} {token}:{start} -> bare basename shared by "
                        f"{len(where)} files; write the full path "
                        f"({', '.join(where[:3])})"
                    )
                    continue
                problems.append(
                    f":{number} {token}:{start} -> bare basename; write {target} instead"
                )
            elif how == "kind":
                problems.append(f":{number} {token}:{start} -> no such file")
                continue

            size = _size(root, target)
            if size is None:  # pragma: no cover - ``_how`` said the file is there
                problems.append(f":{number} {token}:{start} -> no such file")
                continue
            if end is None:
                if not 0 < start <= size:
                    problems.append(f":{number} {target}:{start} -> past the end ({size} lines)")
                continue
            stop = int(end)
            if start > stop:
                problems.append(f":{number} {target}:{start}-{stop} -> the range runs backwards")
                continue
            for cited in (start, stop):
                if not 0 < cited <= size:
                    problems.append(
                        f":{number} {target}:{start}-{stop} -> {cited} is past the end "
                        f"({size} lines)"
                    )
                    break
    return problems
