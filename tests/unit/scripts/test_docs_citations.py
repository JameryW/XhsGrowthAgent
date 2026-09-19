"""Every ``path:line`` we publish has to point at something -- in all 29 documents.

``docs/execution-plane.md`` §8 states the rule and used to be the only document
checked for it.  This file is the corpus-wide half: it sweeps every markdown file we
own, and it carries the fixtures for the rule itself, because the rule's hardest
question is not "does the line resolve" but "**is this token a citation at all**".

Four tokens in this corpus have the same shape and only four ways to end:

| token | where | in the tree? | verdict |
| --- | --- | --- | --- |
| `_wf_actions.py` | `docs/tool-runtime.md` | yes | citation, wrong form |
| `host.containers.internal` | `docs/deployment.md` | no | a host and a port |
| `localhost` | `docs/security.md` | no | a host and a port |
| `postgres` | `CLAUDE.md` | no | an image tag |

The first one is the file `backend/api/routes/_wf_actions.py`, so it is a citation with
its directory missing -- a form the rule reports by finishing the path for the reader.

A rule with an exception list would answer three of those four, and would then have
to be told about every new port.  The fixtures below pin the discriminator that does
not need telling: the tree answers, and it answers **both ways** -- the same text
that is silent in one tree is loud in a tree that has those files.
"""

from __future__ import annotations

from pathlib import Path

from docs_citation_rule import _cited, _rot, documents

REPO = Path(__file__).resolve().parents[3]

# Floors, measured 2026-09-19: 29 documents, 113 citations, 2 of them carrying one.
# ★ 118 -> 113 when §7 of ``execution-plane.md`` was rewritten: the old prose spelled
# its cost model with five more ``file:line`` references than the ruling that replaced
# it needed.  A floor that failed to move with a *legitimate* removal would have to be
# raised every slice; the reason it may move down here is that the removal is visible
# in the same commit, while the narrowing this floor guards against is not.
# A *floor* and not an equality, for the same reason the anchor tables use one:
# adding a reference keeps this green, while a scanner that has quietly narrowed to
# a single document trips it.
#
# ★ Both numbers are the *classified* ones, and both are smaller than the raw text
# says -- that gap is the finding, not a rounding:
#   * raw backticked ``:digits`` tokens: 123 (104 path-shaped + 19 bare).  Seven
#     occurrences are ``localhost:8000``, ``host.containers.internal:9223`` and
#     ``postgres:15``, so the published count is 116.
#   * raw "documents that cite a line": 5 (``docs/deployment.md``,
#     ``docs/security.md``, ``CLAUDE.md`` and the two below).  Under the
#     discriminator the first three carry **no citations at all**.
# A floor copied from the raw count would therefore have been a floor on the wrong
# quantity -- and would have kept three false positives alive by construction.
_MIN_DOCUMENTS = 29
_MIN_CITATIONS = 116
_MIN_DOCUMENTS_WITH_CITATIONS = 2


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _lines(count: int) -> str:
    return "\n".join(f"line {number}" for number in range(1, count + 1))


# ── the corpus ───────────────────────────────────────────────────────────────


def test_the_corpus_is_the_markdown_we_own():
    """The scope rule is a *shape* (no dot component), so it needs pinning twice.

    Both directions matter: a corpus that quietly lost ``docs/`` would make the sweep
    below pass for the wrong reason, and one that quietly gained ``.trellis/`` would
    make every ticket's citations a maintenance burden on code it describes only
    historically.
    """
    corpus = documents(REPO)

    assert "docs/execution-plane.md" in corpus, "the document that named the rule left the corpus"
    assert "docs/tool-runtime.md" in corpus
    assert "CLAUDE.md" in corpus, "the root documents are ours too"
    assert "frontend/README.md" in corpus

    tickets = [path for path in corpus if path.startswith(".trellis/")]
    assert not tickets, f"tickets are a historical record, not maintained prose: {tickets[:3]}"
    vendored = [path for path in corpus if path.startswith((".claude/", ".cursor/"))]
    assert not vendored, f"vendored skill documentation is not ours to fix: {vendored[:3]}"

    assert all(path.endswith(".md") for path in corpus), "the sweep reads prose, not sources"
    assert len(corpus) >= _MIN_DOCUMENTS, (
        f"the corpus shrank to {len(corpus)} documents; if that is real, lower the floor "
        f"deliberately: {corpus}"
    )


def test_every_cited_line_number_in_the_corpus_resolves():
    """The sweep: the whole point of the file."""
    complaints: list[str] = []
    citations = 0
    carrying = 0
    for document in documents(REPO):
        text = (REPO / document).read_text(encoding="utf-8", errors="replace")
        triples, bare = _cited(text, REPO)
        if triples or bare:
            carrying += 1
        citations += len(triples) + len(bare)
        complaints += [f"{document}:{problem}" for problem in _rot(text, REPO)]

    assert carrying >= _MIN_DOCUMENTS_WITH_CITATIONS, (
        f"only {carrying} documents carry a citation -- the scan is not seeing the corpus"
    )
    assert citations >= _MIN_CITATIONS, (
        f"only {citations} citations classified -- the discriminator has started swallowing "
        "real references, which reads exactly like a clean corpus"
    )

    detail = "\n  ".join(complaints)
    assert not complaints, (
        "these documents cite line numbers that do not resolve. Write the full repo-relative "
        f"path -- a bare basename resolves against nothing:\n  {detail}"
    )


# ── the rule's own five failure modes ────────────────────────────────────────


def test_the_rule_reports_every_way_a_reference_rots(tmp_path: Path):
    """Positive control for the rule itself.

    A rule that returned ``[]`` would call every reference in the corpus "fine".  The
    fixture is a miniature of the damage the real documents do, one section per way
    to be wrong: a bare basename, a line past the end, a bare reference past the end,
    a bare reference with nothing before it, and a range whose ends disagree.

    The healthy half of the *same* fixture must stay silent -- a rule that flagged
    everything would satisfy the assertions above and prove nothing.
    """
    _write(tmp_path, "backend/api/routes/_takeover.py", "x = 1\ny = 2\n")
    _write(tmp_path, "backend/api/routes/_wf_actions.py", _lines(11))
    text = (
        "## 1. first\n"
        "\n"
        "`_takeover.py:2` is a basename\n"
        "\n"
        "## 2. second\n"
        "\n"
        "`backend/api/routes/_takeover.py:9` is past the end\n"
        "\n"
        "## 3. third\n"
        "\n"
        "`backend/api/routes/_wf_actions.py:4` is fine, then `:99` is not\n"
        "\n"
        "## 4. fourth\n"
        "\n"
        "`:3` has nothing before it\n"
        "\n"
        "## 5. fifth\n"
        "\n"
        "`backend/api/routes/_wf_actions.py:9-4` runs backwards\n"
    )
    problems = _rot(text, tmp_path)
    assert len(problems) == 5, f"every failure mode must be reported: {problems}"
    assert any("bare basename; write backend/api/routes/_takeover.py" in p for p in problems), (
        problems
    )
    assert any("past the end (2 lines)" in p for p in problems), problems
    assert any("_wf_actions.py past the end (11 lines)" in p for p in problems), problems
    assert any("no path before it" in p for p in problems), problems
    assert any("runs backwards" in p for p in problems), problems

    healthy = _rot("## 1. first\n\n`backend/api/routes/_takeover.py:2` is fine\n", tmp_path)
    assert healthy == [], healthy


def test_a_bare_reference_belongs_to_the_path_before_it_on_its_own_line(tmp_path: Path):
    """A line can cite two files; the bare number belongs to the first one.

    This is the rule's own first bug, found by running it against the real document:
    §0 cites ``_wf_application.py:271`` then ``:275`` then ``_wf_models.py:31`` on one
    line, and a version that collected every path first and every bare number second
    attributed ``:275`` to the 195-line file the line only mentions *afterwards*.

    The fixture **discriminates**: ``:9`` resolves inside the 11-line file but is past
    the end of the 3-line one, so a misattributing rule cannot stay silent here.
    """
    _write(tmp_path, "backend/api/routes/_wf_application.py", _lines(11))
    _write(tmp_path, "backend/api/routes/_wf_models.py", _lines(3))
    line = (
        "`backend/api/routes/_wf_application.py:4` then `:9` "
        "then `backend/api/routes/_wf_models.py:2`\n"
    )
    assert _rot("## 1. one line, two files\n\n" + line, tmp_path) == [], "both references resolve"

    past = line.replace("`:9`", "`:99`")
    problems = _rot("## 1. one line, two files\n\n" + past, tmp_path)
    assert len(problems) == 1, problems
    assert "_wf_application.py past the end (11 lines)" in problems[0], problems[0]


# ── the discriminator ────────────────────────────────────────────────────────


def test_a_host_and_a_port_is_not_a_citation(tmp_path: Path):
    """The three shapes the corpus actually contains, none of which is a citation.

    ``docs/deployment.md`` says ``host.containers.internal:9223``, ``docs/security.md``
    says ``localhost:8000``, ``CLAUDE.md`` says ``postgres:15``.  All three are
    backticked, all three end in ``:digits``, none of them names a file.
    """
    text = (
        "## 1. endpoints\n"
        "\n"
        "`XHS_CDP_ENDPOINT` or `host.containers.internal:9223`, default `localhost:8000`\n"
        "\n"
        "## 2. images\n"
        "\n"
        "the `pgvector/pgvector:pg15` image (not `postgres:15`)\n"
    )
    assert _rot(text, tmp_path) == [], "a port is not a line number"
    triples, bare = _cited(text, tmp_path)
    assert (triples, bare) == ([], []), "and it must not inflate the published citation count"

    # The other half of "not a citation": a port must not become the thing the next
    # bare ``:N`` belongs to.  ``:12`` on that line is attributed to whatever path
    # preceded it *in its section*, so if the port counted, this number would stop
    # being an orphan -- and the orphan complaint is the only visible difference.
    followed = chr(10).join(["## 3. adopted", "", "`localhost:8000` then `:12`", ""])
    problems = _rot(followed, tmp_path)
    assert len(problems) == 1, problems
    assert "no path before it" in problems[0], problems


def test_the_discriminator_reads_the_tree_and_not_a_word_list(tmp_path: Path):
    """The same three tokens, in a tree that *does* have files by those names.

    This is the discriminating half of the fixture above: identical text, opposite
    verdict, and the only thing that changed is the tree.  It is also the fixture
    that fails if anyone ever replaces the discriminator with a list of known
    hostnames -- the list would keep calling these three "not a citation" here.
    """
    (tmp_path / "deep" / "nested").mkdir(parents=True)
    for name in ("localhost", "postgres", "host.containers.internal"):
        _write(tmp_path, f"deep/nested/{name}", _lines(3))
    text = (
        "## 1. endpoints\n"
        "\n"
        "`host.containers.internal:9223` and `localhost:8000`, plus `postgres:15`\n"
    )
    problems = _rot(text, tmp_path)
    named = [p for p in problems if "bare basename" in p]
    assert len(named) == 3, f"all three name real files now, so all three are citations: {problems}"
    assert "deep/nested/localhost" in " ".join(named)
    assert "deep/nested/postgres" in " ".join(named)


def test_a_bare_basename_that_names_no_file_is_still_a_citation(tmp_path: Path):
    """Attesting the *kind* is enough, and this is the only thing that catches a typo.

    ``_wf_actins.py`` is not a file anywhere, so "does the tree have this name" says
    no -- and a rule that stopped there would silently ignore a misspelled reference.
    What makes it a citation is that the tree has files of that type.  The fixture
    **discriminates**: ``localhost:8000`` sits on the next line with the same shape
    and no suffix, so a rule that answered "citation" from the shape alone fails here.
    """
    _write(tmp_path, "backend/api/routes/_wf_actions.py", _lines(11))
    text = (
        "## 1. typo\n"
        "\n"
        "`_wf_actins.py:101` is a misspelling\n"
        "\n"
        "## 2. port\n"
        "\n"
        "`localhost:8000` is a port, and it has no file type at all\n"
    )
    problems = _rot(text, tmp_path)
    assert len(problems) == 1, problems
    assert "_wf_actins.py:101 -> no such file" in problems[0], problems[0]


def test_an_ambiguous_basename_is_reported_rather_than_guessed(tmp_path: Path):
    """94 names in the tree are ambiguous (``__init__.py``, ``conftest.py``, ...).

    So "which file did you mean" has no answer sometimes, and the complaint has to say
    so instead of picking one.  The fixture holds both cases side by side, because the
    two messages must differ: a rule that always named the first match would pass a
    single-case fixture.
    """
    _write(tmp_path, "backend/api/routes/_wf_actions.py", _lines(11))
    _write(tmp_path, "backend/tools/_wf_actions.py", _lines(11))
    _write(tmp_path, "backend/api/routes/_takeover.py", _lines(2))
    text = "## 1. ambiguous\n\n`_wf_actions.py:1`\n\n## 2. unique\n\n`_takeover.py:1`\n"
    problems = _rot(text, tmp_path)
    assert len(problems) == 2, problems
    ambiguous = [p for p in problems if "shared by 2 files" in p]
    assert len(ambiguous) == 1, problems
    assert "backend/api/routes/_wf_actions.py" in ambiguous[0]
    assert "backend/tools/_wf_actions.py" in ambiguous[0]
    unique = [p for p in problems if "write backend/api/routes/_takeover.py instead" in p]
    assert len(unique) == 1, problems


def test_a_wrong_full_path_is_still_reported_as_missing(tmp_path: Path):
    """A slash makes the token a citation no matter what the tree contains.

    Without this, the fix for the host:port false positive would have quietly opened
    the door to the opposite mistake: a full path that drifted out of existence.
    """
    _write(tmp_path, "backend/api/routes/_runner.py", _lines(5))
    text = "## 1. drift\n\n`backend/api/routes/_runner.pyx:2` and `backend/api/old/_runner.py:2`\n"
    problems = _rot(text, tmp_path)
    assert len(problems) == 2, problems
    assert all("no such file" in p for p in problems), problems
