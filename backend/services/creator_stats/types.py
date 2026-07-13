"""Internal DTOs for creator-center account/note statistics.

Fields mirror the Xiaohongshu creator statistics surface
(https://creator.xiaohongshu.com/statistics/account/v2) after boundary mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CreativeMode = Literal["trend", "brief", "free"]


@dataclass
class AccountStatsOverview:
    """Account-level performance snapshot from creator statistics."""

    account_id: str
    creator_user_id: str = ""
    creator_name: str = ""
    red_id: str = ""
    avatar_url: str = ""
    bio: str = ""
    creator_role: str = ""
    zone: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    collects: int = 0
    shares: int = 0
    fans: int = 0
    note_count: int = 0
    period: str = "30d"
    synced_at: str = ""
    source: str = "creator_statistics"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountStatsOverview:
        return cls(
            account_id=str(data.get("account_id", "")),
            creator_user_id=str(data.get("creator_user_id") or ""),
            creator_name=str(data.get("creator_name") or ""),
            red_id=str(data.get("red_id") or ""),
            avatar_url=str(data.get("avatar_url") or ""),
            bio=str(data.get("bio") or ""),
            creator_role=str(data.get("creator_role") or ""),
            zone=str(data.get("zone") or ""),
            views=int(data.get("views") or 0),
            likes=int(data.get("likes") or 0),
            comments=int(data.get("comments") or 0),
            collects=int(data.get("collects") or 0),
            shares=int(data.get("shares") or 0),
            fans=int(data.get("fans") or 0),
            note_count=int(data.get("note_count") or 0),
            period=str(data.get("period") or "30d"),
            synced_at=str(data.get("synced_at") or ""),
            source=str(data.get("source") or "creator_statistics"),
        )


@dataclass
class NoteStats:
    """Note-level performance row from creator statistics."""

    note_id: str
    account_id: str
    title: str = ""
    # Snippet of note body for niche infer / analysis (truncated on normalize)
    body_text: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    collects: int = 0
    shares: int = 0
    published_at: str = ""
    content_type: str = "note"  # note | video | carousel
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""
    engagement_rate: float = 0.0
    synced_at: str = ""
    source: str = "creator_statistics"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoteStats:
        tags = data.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        return cls(
            note_id=str(data.get("note_id") or data.get("id") or ""),
            account_id=str(data.get("account_id") or ""),
            title=str(data.get("title") or ""),
            body_text=str(
                data.get("body_text")
                or data.get("body")
                or data.get("content")
                or data.get("desc")
                or ""
            ),
            views=int(data.get("views") or 0),
            likes=int(data.get("likes") or 0),
            comments=int(data.get("comments") or 0),
            collects=int(data.get("collects") or 0),
            shares=int(data.get("shares") or 0),
            published_at=str(data.get("published_at") or data.get("publish_time") or ""),
            content_type=str(data.get("content_type") or data.get("note_type") or "note"),
            tags=[str(t) for t in tags],
            cover_url=str(data.get("cover_url") or ""),
            engagement_rate=float(data.get("engagement_rate") or 0.0),
            synced_at=str(data.get("synced_at") or ""),
            source=str(data.get("source") or "creator_statistics"),
        )

    def recompute_engagement_rate(self) -> float:
        if self.views <= 0:
            self.engagement_rate = 0.0
            return 0.0
        total = self.likes + self.comments + self.collects + self.shares
        self.engagement_rate = round(total / self.views, 4)
        return self.engagement_rate


@dataclass
class CreatorStatsBundle:
    """Normalized account + note payload ready for persistence."""

    account: AccountStatsOverview
    notes: list[NoteStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "notes": [n.to_dict() for n in self.notes],
        }


@dataclass
class StyleFinding:
    """Data-backed creative style finding derived from note stats."""

    finding_type: str  # tone | topic | format | timing | hashtag
    label: str
    evidence: str
    score: float = 0.0
    sample_count: int = 0
    note_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CreativeSuggestion:
    """Actionable creative advice consumable by trend/brief/free modes."""

    mode: CreativeMode
    category: str  # style | topic | format | timing | cold_start
    title: str
    advice: str
    priority: int = 1
    evidence: str = ""
    related_note_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    """Output of creative analysis over persisted note stats."""

    account_id: str
    findings: list[StyleFinding] = field(default_factory=list)
    styles_deposited: int = 0
    materials_deposited: int = 0
    plays_deposited: int = 0
    note_count: int = 0
    avg_engagement_rate: float = 0.0
    top_note_ids: list[str] = field(default_factory=list)
    cold_start: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "findings": [f.to_dict() for f in self.findings],
            "styles_deposited": self.styles_deposited,
            "materials_deposited": self.materials_deposited,
            "plays_deposited": self.plays_deposited,
            "note_count": self.note_count,
            "avg_engagement_rate": self.avg_engagement_rate,
            "top_note_ids": self.top_note_ids,
            "cold_start": self.cold_start,
        }


@dataclass
class SyncResult:
    """Primary observables returned by the sync/import entry point."""

    account_id: str
    notes_imported: int = 0
    notes_updated: int = 0
    account_synced: bool = False
    analysis: AnalysisResult | None = None
    suggestions: dict[str, list[CreativeSuggestion]] = field(default_factory=dict)
    source: str = "fixture"
    error: str | None = None
    niche_resolution: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "notes_imported": self.notes_imported,
            "notes_updated": self.notes_updated,
            "account_synced": self.account_synced,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "suggestions": {
                mode: [s.to_dict() for s in items] for mode, items in self.suggestions.items()
            },
            "source": self.source,
            "error": self.error,
            "niche_resolution": self.niche_resolution,
        }
