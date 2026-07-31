"""Internal DTOs for creator-center account/note statistics.

Fields mirror the Xiaohongshu creator statistics surface
(https://creator.xiaohongshu.com/statistics/account/v2) after boundary mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CreativeMode = Literal["trend", "brief", "free"]
QualityDimensionKey = Literal[
    "engagement",
    "save_value",
    "title_craft",
    "body_craft",
    "consistency",
]
QualityGrade = Literal["strong", "developing", "needs_attention", "insufficient_data"]
QualityConfidence = Literal["low", "medium", "high"]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    """Keep JSON DTO fields predictable when reading older database rows."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict_map(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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
    # Public aggregate audience signals returned by Creator Center.  These
    # remain JSON-shaped because the platform adds/removes segments over time.
    audience_sources: list[dict[str, Any]] = field(default_factory=list)
    audience_view_periods: list[dict[str, Any]] = field(default_factory=list)
    audience_profile: list[dict[str, Any]] = field(default_factory=list)
    detail_metrics: dict[str, Any] = field(default_factory=dict)
    # Opaque identity of the atomic Creator Stats import. Older rows may not
    # have it; the storage reader derives a compatible digest from all notes.
    snapshot_id: str | None = None

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
            snapshot_id=str(data.get("snapshot_id") or "") or None,
            source=str(data.get("source") or "creator_statistics"),
            audience_sources=_dict_list(data.get("audience_sources")),
            audience_view_periods=_dict_list(data.get("audience_view_periods")),
            audience_profile=_dict_list(data.get("audience_profile")),
            detail_metrics=_dict_map(data.get("detail_metrics")),
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
    # Optional per-note breakdowns.  Current Creator Center accounts expose
    # these only for some note/detail surfaces, so absence is a valid state.
    view_sources: list[dict[str, Any]] = field(default_factory=list)
    audience_profile: list[dict[str, Any]] = field(default_factory=list)
    audience_trend: list[dict[str, Any]] = field(default_factory=list)
    detail_metrics: dict[str, Any] = field(default_factory=dict)

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
            view_sources=_dict_list(data.get("view_sources")),
            audience_profile=_dict_list(data.get("audience_profile")),
            audience_trend=_dict_list(data.get("audience_trend")),
            detail_metrics=_dict_map(data.get("detail_metrics")),
        )

    def recompute_engagement_rate(self) -> float:
        if self.views <= 0:
            self.engagement_rate = 0.0
            return 0.0
        total = self.likes + self.comments + self.collects + self.shares
        self.engagement_rate = round(total / self.views, 4)
        return self.engagement_rate


@dataclass
class NoteStatsPage:
    """Canonical, cursor-paginated historical-note fact page.

    ``engagement_rate`` in every item is a fraction in the inclusive 0--1
    domain.  Presentation layers may format it as a percentage, but must not
    change the API value or infer a second unit.
    """

    account_id: str
    items: list[NoteStats] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    next_cursor: str | None = None
    data_as_of: str = ""
    snapshot_id: str | None = None
    published_from: str | None = None
    published_to: str | None = None
    sort: str = "published_at_desc"

    def to_dict(self) -> dict[str, Any]:
        data_as_of = self.data_as_of or None
        items = []
        for item in self.items:
            row = item.to_dict()
            # Every row carries the same taxonomy and its own source timestamp
            # so list consumers do not need to infer semantics from the URL.
            row.update(
                {
                    "subject_type": "imported_note",
                    "subject_id": item.note_id,
                    "scope": "account_history",
                    "assessment_type": "historical_performance",
                    "status": "ready",
                    "algorithm_version": "historical_quality.v1",
                    "data_as_of": item.synced_at or data_as_of,
                    "note_synced_at": item.synced_at or None,
                    "snapshot_id": self.snapshot_id,
                }
            )
            items.append(row)
        return {
            "account_id": self.account_id,
            "items": items,
            "total": self.total,
            "limit": self.limit,
            "next_cursor": self.next_cursor,
            "data_as_of": data_as_of,
            "snapshot_id": self.snapshot_id,
            "query": {
                "sort": self.sort,
                "published_from": self.published_from,
                "published_to": self.published_to,
            },
            "engagement_rate_unit": "fraction",
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "algorithm_version": "historical_quality.v1",
            "status": "ready" if items or self.total else "unavailable",
            "contract_version": "quality_consistency.v2",
        }


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
class QualityDimension:
    """One transparent historical creative-quality dimension.

    Scores are heuristic 0--100 signals.  Consumers must use the parent
    report's ``insufficient_data`` flag before treating them as an overall
    quality judgement.
    """

    key: QualityDimensionKey
    score: float = 0.0
    evidence: str = ""
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "score": self.score,
            "evidence": self.evidence,
            "available": self.available,
        }


@dataclass
class QualityInsight:
    """A metric-backed account strength or shortfall."""

    dimension: str
    title: str
    evidence: str
    related_note_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "title": self.title,
            "evidence": self.evidence,
            "related_note_ids": self.related_note_ids,
        }


@dataclass
class QualityRecommendation:
    """A prioritized next-post action grounded in historical metrics."""

    priority: int
    dimension: str
    title: str
    advice: str
    evidence: str
    related_note_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "dimension": self.dimension,
            "title": self.title,
            "advice": self.advice,
            "evidence": self.evidence,
            "related_note_ids": self.related_note_ids,
        }


@dataclass
class CreatorQualityReport:
    """Read-only quality report over imported account history or one note."""

    account_id: str
    note_id: str = ""
    total_notes: int = 0
    notes_analyzed: int = 0
    scope: str = "account_history"
    overall_score: float | None = None
    grade: QualityGrade = "insufficient_data"
    confidence: QualityConfidence = "low"
    summary: str = ""
    dimensions: list[QualityDimension] = field(default_factory=list)
    strengths: list[QualityInsight] = field(default_factory=list)
    weaknesses: list[QualityInsight] = field(default_factory=list)
    recommendations: list[QualityRecommendation] = field(default_factory=list)
    cold_start: bool = False
    insufficient_data: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "note_id": self.note_id,
            "total_notes": self.total_notes,
            "notes_analyzed": self.notes_analyzed,
            "scope": self.scope,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "confidence": self.confidence,
            "summary": self.summary,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "strengths": [item.to_dict() for item in self.strengths],
            "weaknesses": [item.to_dict() for item in self.weaknesses],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "cold_start": self.cold_start,
            "insufficient_data": self.insufficient_data,
        }


# Machine-readable sync failure classes (UI/ops routing).
ERROR_AUTH_EXPIRED = "AUTH_EXPIRED"
ERROR_BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
ERROR_FETCH_FAILED = "FETCH_FAILED"
ERROR_ALREADY_RUNNING = "ALREADY_RUNNING"
ERROR_EMPTY_SHELL = "EMPTY_SHELL"


def classify_sync_error(message: str | None, *, status_code: int | None = None) -> str | None:
    """Map free-text / HTTP status into a stable ``error_code``."""
    if not message and status_code is None:
        return None
    if status_code in (401, 403):
        return ERROR_AUTH_EXPIRED
    text = str(message or "").lower()
    if any(
        token in text
        for token in (
            "empty shell",
            "empty_shell",
            "notes collapsed",
        )
    ):
        return ERROR_EMPTY_SHELL
    if any(
        token in text
        for token in (
            "login page",
            "auth failed",
            "re-login",
            "logged in",
            "stale_id",
            "扫码",
            "登录",
            "auth expired",
        )
    ):
        return ERROR_AUTH_EXPIRED
    if any(
        token in text
        for token in (
            "browser",
            "cdp",
            "浏览器",
            "cdp_endpoint",
            "cookie required",
            "no logged-in browser context",
            "playwright not installed",
        )
    ):
        return ERROR_BROWSER_UNAVAILABLE
    if "already_running" in text:
        return ERROR_ALREADY_RUNNING
    return ERROR_FETCH_FAILED


@dataclass
class SyncResult:
    """Primary observables returned by the sync/import entry point."""

    account_id: str
    notes_imported: int = 0
    notes_updated: int = 0
    notes_deleted: int = 0
    account_synced: bool = False
    analysis: AnalysisResult | None = None
    suggestions: dict[str, list[CreativeSuggestion]] = field(default_factory=dict)
    source: str = "fixture"
    error: str | None = None
    error_code: str | None = None
    niche_resolution: dict[str, Any] | None = None
    # Soft risk: crawl completed but data looks hollow (empty shell after prior notes).
    # Scheduler should cool down without treating it as a full live success.
    soft_risk: bool = False
    soft_risk_reason: str | None = None

    def __post_init__(self) -> None:
        # Keep error_code filled for failed results so clients never have to
        # re-parse free-text messages.
        if self.error and not self.error_code:
            self.error_code = classify_sync_error(self.error)
        if self.soft_risk and not self.error_code:
            self.error_code = ERROR_EMPTY_SHELL

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "notes_imported": self.notes_imported,
            "notes_updated": self.notes_updated,
            "notes_deleted": self.notes_deleted,
            "account_synced": self.account_synced,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "suggestions": {
                mode: [s.to_dict() for s in items] for mode, items in self.suggestions.items()
            },
            "source": self.source,
            "error": self.error,
            "error_code": self.error_code,
            "niche_resolution": self.niche_resolution,
            "soft_risk": self.soft_risk,
            "soft_risk_reason": self.soft_risk_reason,
        }
