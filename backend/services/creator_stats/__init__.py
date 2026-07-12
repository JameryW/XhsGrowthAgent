"""Creator-center statistics import, analysis, and creative suggestions."""

from backend.services.creator_stats.analyze import (
    analyze_notes,
    as_fraction_engagement_rate,
    run_analysis,
)
from backend.services.creator_stats.client import (
    CREATOR_STATS_PAGE,
    CreatorStatsClient,
    CreatorStatsFetchError,
    FixtureTransport,
    normalize_period,
    period_to_date_type,
)
from backend.services.creator_stats.normalize import (
    extract_note_items,
    normalize_account_overview,
    normalize_bundle,
    normalize_note,
    normalize_note_list,
)
from backend.services.creator_stats.pipeline import (
    import_bundle,
    sync_account_stats,
    sync_from_fixture,
    sync_from_payload,
)
from backend.services.creator_stats.suggestions import (
    build_mode_creative_context,
    format_suggestions_context,
    get_suggestions_for_mode,
    suggestions_from_analysis,
)
from backend.services.creator_stats.types import (
    AccountStatsOverview,
    AnalysisResult,
    CreativeMode,
    CreativeSuggestion,
    CreatorStatsBundle,
    NoteStats,
    StyleFinding,
    SyncResult,
)

__all__ = [
    "CREATOR_STATS_PAGE",
    "AccountStatsOverview",
    "AnalysisResult",
    "CreativeMode",
    "CreativeSuggestion",
    "CreatorStatsBundle",
    "CreatorStatsClient",
    "CreatorStatsFetchError",
    "FixtureTransport",
    "NoteStats",
    "StyleFinding",
    "SyncResult",
    "analyze_notes",
    "as_fraction_engagement_rate",
    "build_mode_creative_context",
    "format_suggestions_context",
    "get_suggestions_for_mode",
    "import_bundle",
    "extract_note_items",
    "normalize_account_overview",
    "normalize_bundle",
    "normalize_note",
    "normalize_note_list",
    "normalize_period",
    "period_to_date_type",
    "run_analysis",
    "suggestions_from_analysis",
    "sync_account_stats",
    "sync_from_fixture",
    "sync_from_payload",
]
