"""Platform post identity — the one place that decides what counts as an id.

Both ends of the outcome-learning loop have to agree on "which platform post
is this workflow's output": the publish path stamps an id into
``publish_result`` (``agents/publisher.py``) and the analytics read path
matches workflow rows against imported Creator Center notes
(``api/routes/analytics.py``).  Each side used to carry its own copy of the
rule, so the only thing keeping them in agreement was that the read side
happened to normalize before comparing.

Everything here is pure: no I/O, and no mutation of the rows handed in.  That
is what makes a resolved link *recomputable* — the same inputs give the same
resolution whether it is computed inside an HTTP request or replayed later by
a non-request caller (the sync-time weak-label backfill in P3-S3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

__all__ = [
    "LinkGroup",
    "LinkResolution",
    "normalize_platform_post_id",
    "resolve_platform_links",
]

LinkStatus = Literal["linked", "ambiguous", "unmatched"]


def normalize_platform_post_id(value: Any) -> str:
    """Normalize a platform post identifier without accepting synthetic IDs.

    ``mock_*`` ids (dry-run publishes) and ``workflow:<thread>`` display keys
    are not platform identities, so they normalize to the empty string.  A
    full post URL keeps only its last path segment, so the same note written
    as a URL or as a bare id compares equal.  Callers compare this result,
    never the raw value.
    """
    raw = str(value or "").strip()
    if not raw or raw.startswith("mock_") or raw.startswith("workflow:"):
        return ""
    if "://" in raw:
        parsed = urlparse(raw)
        path_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if path_id:
            raw = path_id
    return raw


@dataclass(frozen=True)
class LinkGroup:
    """Imported notes claiming one normalized platform id, and the workflows claiming it too."""

    platform_post_id: str
    workflow_indices: tuple[int, ...]
    imported_indices: tuple[int, ...]

    @property
    def status(self) -> LinkStatus:
        """``linked`` only when exactly one row on each side claims the id.

        One imported note with no workflow claim is simply unmatched — it
        stays an independent row.  Several imported claims on the SAME id are
        already ambiguous on their own (they would otherwise silently pick a
        winner), so ambiguity is decided by either side having more than one
        claimant.
        """
        one_each = len(self.workflow_indices) == 1 and len(self.imported_indices) == 1
        if one_each:
            return "linked"
        if not self.workflow_indices and len(self.imported_indices) == 1:
            return "unmatched"
        return "ambiguous"


@dataclass(frozen=True)
class LinkResolution:
    """Deterministic outcome of matching workflow rows to imported notes.

    Indices point into the sequences handed to :func:`resolve_platform_links`,
    so a caller applies the resolution to its own rows instead of receiving
    mutated copies.  ``groups`` follows the imported side's first-seen order;
    ``idless_imported`` are rows carrying no explicit id at all.
    """

    groups: tuple[LinkGroup, ...]
    idless_imported: tuple[int, ...]

    @property
    def linked(self) -> tuple[tuple[int, int], ...]:
        """``(workflow_index, imported_index)`` pairs that resolved one-to-one."""
        return tuple(
            (group.workflow_indices[0], group.imported_indices[0])
            for group in self.groups
            if group.status == "linked"
        )

    @property
    def appended_imported(self) -> tuple[int, ...]:
        """Imported rows the caller must append, preserving the original order.

        A linked note is represented by its workflow row, so only the
        ambiguous/unmatched groups and the id-less rows remain.
        """
        pending = [
            index
            for group in self.groups
            if group.status != "linked"
            for index in group.imported_indices
        ]
        pending.extend(self.idless_imported)
        return tuple(pending)


def resolve_platform_links(
    workflow_rows: Sequence[Mapping[str, Any]],
    imported_rows: Sequence[Mapping[str, Any]],
) -> LinkResolution:
    """Match workflow rows to imported notes by explicit platform identity only.

    Missing or synthetic workflow ids never collapse an imported note, and
    duplicate workflow claims stay separate as ``ambiguous``.  Neither
    sequence nor any row inside it is modified.
    """
    workflow_by_id: dict[str, list[int]] = {}
    for wf_index, workflow in enumerate(workflow_rows):
        platform_id = normalize_platform_post_id(workflow.get("platform_post_id"))
        if platform_id:
            workflow_by_id.setdefault(platform_id, []).append(wf_index)

    imported_by_id: dict[str, list[int]] = {}
    idless: list[int] = []
    for imp_index, imported in enumerate(imported_rows):
        platform_id = normalize_platform_post_id(
            imported.get("platform_post_id") or imported.get("id")
        )
        if platform_id:
            imported_by_id.setdefault(platform_id, []).append(imp_index)
        else:
            idless.append(imp_index)

    return LinkResolution(
        groups=tuple(
            LinkGroup(
                platform_post_id=platform_id,
                workflow_indices=tuple(workflow_by_id.get(platform_id, ())),
                imported_indices=tuple(imported_indices),
            )
            for platform_id, imported_indices in imported_by_id.items()
        ),
        idless_imported=tuple(idless),
    )
