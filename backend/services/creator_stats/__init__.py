"""Creator-center statistics import, analysis, and creative suggestions.

All re-exports are lazy via ``__getattr__`` (PEP 562). ``analyze`` pulls in
langgraph.store.base → langchain_core (~0.4s) at import; ``client`` pulls a
CDP/transport chain. Eagerly importing them here made every
``backend.services.creator_stats.X`` submodule import pay that cost, including
the app cold-start chain (db.creator_stats → this package) and test
collection. Submodule imports (``from backend.services.creator_stats import
pipeline``) resolve normally; symbol imports resolve via __getattr__;
``import *`` works via __dir__.
"""

from typing import Any

_LAZY_EXPORTS = {
    "analyze_notes": ("backend.services.creator_stats.analyze", "analyze_notes"),
    "as_fraction_engagement_rate": (
        "backend.services.creator_stats.analyze",
        "as_fraction_engagement_rate",
    ),
    "run_analysis": ("backend.services.creator_stats.analyze", "run_analysis"),
    "CREATOR_PROFILE_PATH": ("backend.services.creator_stats.client", "CREATOR_PROFILE_PATH"),
    "CREATOR_STATS_PAGE": ("backend.services.creator_stats.client", "CREATOR_STATS_PAGE"),
    "CreatorStatsClient": ("backend.services.creator_stats.client", "CreatorStatsClient"),
    "CreatorStatsFetchError": (
        "backend.services.creator_stats.client",
        "CreatorStatsFetchError",
    ),
    "FixtureTransport": ("backend.services.creator_stats.client", "FixtureTransport"),
    "normalize_period": ("backend.services.creator_stats.client", "normalize_period"),
    "period_to_date_type": ("backend.services.creator_stats.client", "period_to_date_type"),
    "extract_note_items": ("backend.services.creator_stats.normalize", "extract_note_items"),
    "normalize_account_overview": (
        "backend.services.creator_stats.normalize",
        "normalize_account_overview",
    ),
    "normalize_account_profile": (
        "backend.services.creator_stats.normalize",
        "normalize_account_profile",
    ),
    "normalize_bundle": ("backend.services.creator_stats.normalize", "normalize_bundle"),
    "normalize_note": ("backend.services.creator_stats.normalize", "normalize_note"),
    "normalize_note_list": ("backend.services.creator_stats.normalize", "normalize_note_list"),
    "clear_post_login_sync_gate": (
        "backend.services.creator_stats.pipeline",
        "clear_post_login_sync_gate",
    ),
    "import_bundle": ("backend.services.creator_stats.pipeline", "import_bundle"),
    "preflight_creator_login": (
        "backend.services.creator_stats.pipeline",
        "preflight_creator_login",
    ),
    "sync_account_stats": ("backend.services.creator_stats.pipeline", "sync_account_stats"),
    "sync_after_login": ("backend.services.creator_stats.pipeline", "sync_after_login"),
    "sync_all_active_accounts": (
        "backend.services.creator_stats.pipeline",
        "sync_all_active_accounts",
    ),
    "sync_from_fixture": ("backend.services.creator_stats.pipeline", "sync_from_fixture"),
    "sync_from_payload": ("backend.services.creator_stats.pipeline", "sync_from_payload"),
    "MIN_NOTES_FOR_OVERALL_SCORE": (
        "backend.services.creator_stats.quality",
        "MIN_NOTES_FOR_OVERALL_SCORE",
    ),
    "SCOPE_ALL_IMPORTED_HISTORY": (
        "backend.services.creator_stats.quality",
        "SCOPE_ALL_IMPORTED_HISTORY",
    ),
    "SCOPE_SINGLE_IMPORTED_NOTE": (
        "backend.services.creator_stats.quality",
        "SCOPE_SINGLE_IMPORTED_NOTE",
    ),
    "analyze_historical_quality": (
        "backend.services.creator_stats.quality",
        "analyze_historical_quality",
    ),
    "analyze_note_quality": (
        "backend.services.creator_stats.quality",
        "analyze_note_quality",
    ),
    "build_mode_creative_context": (
        "backend.services.creator_stats.suggestions",
        "build_mode_creative_context",
    ),
    "format_suggestions_context": (
        "backend.services.creator_stats.suggestions",
        "format_suggestions_context",
    ),
    "get_suggestions_for_mode": (
        "backend.services.creator_stats.suggestions",
        "get_suggestions_for_mode",
    ),
    "suggestions_from_analysis": (
        "backend.services.creator_stats.suggestions",
        "suggestions_from_analysis",
    ),
    "ERROR_ALREADY_RUNNING": ("backend.services.creator_stats.types", "ERROR_ALREADY_RUNNING"),
    "ERROR_AUTH_EXPIRED": ("backend.services.creator_stats.types", "ERROR_AUTH_EXPIRED"),
    "ERROR_BROWSER_UNAVAILABLE": (
        "backend.services.creator_stats.types",
        "ERROR_BROWSER_UNAVAILABLE",
    ),
    "ERROR_EMPTY_SHELL": ("backend.services.creator_stats.types", "ERROR_EMPTY_SHELL"),
    "ERROR_FETCH_FAILED": ("backend.services.creator_stats.types", "ERROR_FETCH_FAILED"),
    "AccountStatsOverview": ("backend.services.creator_stats.types", "AccountStatsOverview"),
    "AnalysisResult": ("backend.services.creator_stats.types", "AnalysisResult"),
    "CreativeMode": ("backend.services.creator_stats.types", "CreativeMode"),
    "CreativeSuggestion": ("backend.services.creator_stats.types", "CreativeSuggestion"),
    "CreatorQualityReport": ("backend.services.creator_stats.types", "CreatorQualityReport"),
    "CreatorStatsBundle": ("backend.services.creator_stats.types", "CreatorStatsBundle"),
    "NoteStats": ("backend.services.creator_stats.types", "NoteStats"),
    "QualityConfidence": ("backend.services.creator_stats.types", "QualityConfidence"),
    "QualityDimension": ("backend.services.creator_stats.types", "QualityDimension"),
    "QualityDimensionKey": ("backend.services.creator_stats.types", "QualityDimensionKey"),
    "QualityGrade": ("backend.services.creator_stats.types", "QualityGrade"),
    "QualityInsight": ("backend.services.creator_stats.types", "QualityInsight"),
    "QualityRecommendation": (
        "backend.services.creator_stats.types",
        "QualityRecommendation",
    ),
    "StyleFinding": ("backend.services.creator_stats.types", "StyleFinding"),
    "SyncResult": ("backend.services.creator_stats.types", "SyncResult"),
    "classify_sync_error": ("backend.services.creator_stats.types", "classify_sync_error"),
}

__all__ = [
    "CREATOR_PROFILE_PATH",
    "CREATOR_STATS_PAGE",
    "ERROR_ALREADY_RUNNING",
    "ERROR_AUTH_EXPIRED",
    "ERROR_BROWSER_UNAVAILABLE",
    "ERROR_EMPTY_SHELL",
    "ERROR_FETCH_FAILED",
    "AccountStatsOverview",
    "AnalysisResult",
    "CreativeMode",
    "CreativeSuggestion",
    "CreatorQualityReport",
    "CreatorStatsBundle",
    "CreatorStatsClient",
    "CreatorStatsFetchError",
    "FixtureTransport",
    "NoteStats",
    "QualityConfidence",
    "QualityDimension",
    "QualityDimensionKey",
    "QualityGrade",
    "QualityInsight",
    "QualityRecommendation",
    "StyleFinding",
    "SyncResult",
    "analyze_notes",
    "analyze_historical_quality",
    "analyze_note_quality",
    "as_fraction_engagement_rate",
    "build_mode_creative_context",
    "classify_sync_error",
    "clear_post_login_sync_gate",
    "format_suggestions_context",
    "get_suggestions_for_mode",
    "import_bundle",
    "preflight_creator_login",
    "sync_after_login",
    "sync_all_active_accounts",
    "MIN_NOTES_FOR_OVERALL_SCORE",
    "extract_note_items",
    "normalize_account_profile",
    "normalize_account_overview",
    "normalize_bundle",
    "normalize_note",
    "normalize_note_list",
    "normalize_period",
    "period_to_date_type",
    "run_analysis",
    "SCOPE_ALL_IMPORTED_HISTORY",
    "SCOPE_SINGLE_IMPORTED_NOTE",
    "suggestions_from_analysis",
    "sync_account_stats",
    "sync_from_fixture",
    "sync_from_payload",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.services.creator_stats' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
