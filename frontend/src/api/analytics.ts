import client from './client'
import type {
  GrowthReport,
  PerformanceData,
  CostData,
  AnalyticsPeriodSummary,
} from '@/types/analytics'
import type { NicheResolution } from './accounts'
import { QUALITY_CONSISTENCY_V2_ENABLED } from '@/constants/qualityConsistency'

// 获取增长报告
export async function getGrowthReport(
  accountId: string,
  period: string = 'weekly'
): Promise<GrowthReport> {
  return client.get(`/analytics/report/${accountId}`, { params: { period } })
}

// 获取帖子表现
export async function getPerformance(
  accountId: string,
  period: string = 'weekly',
  limit: number = 20
): Promise<PerformanceData> {
  return client.get(`/analytics/performance/${accountId}`, { params: { period, limit } })
}

// 获取成本统计
export async function getCosts(period: string = 'weekly'): Promise<CostData> {
  return client.get('/analytics/costs', { params: { period } })
}

// Single-request dashboard bundle (avoids 3× cold-start cost)
export async function getDashboard(
  accountId: string,
  period: string = 'weekly',
  limit: number = 20
): Promise<{
  report: GrowthReport
  performance: PerformanceData
  costs: CostData
  period_summary: AnalyticsPeriodSummary
  account_id?: string
  data_as_of?: string | null
  snapshot_id?: string | null
  engagement_rate_unit?: 'fraction' | 'percent' | string
  contract_version?: string | null
}> {
  return client.get(`/analytics/dashboard/${accountId}`, { params: { period, limit } })
}

// ── Creator-center stats import ────────────────────────────────────────────

export interface CreatorAggregatePoint {
  title?: string
  name?: string
  label?: string
  value?: number | string
  count?: number | string
  color?: string
  start_point?: string
  end_point?: string
  [key: string]: unknown
}

export interface CreatorNoteStats {
  note_id: string
  account_id: string
  title: string
  views: number
  likes: number
  comments: number
  collects: number
  shares: number
  published_at: string
  content_type: string
  tags: string[]
  cover_url: string
  engagement_rate: number
  synced_at: string
  source: string
  body_text?: string
  view_sources?: CreatorAggregatePoint[]
  audience_profile?: CreatorAggregatePoint[]
  audience_trend?: CreatorAggregatePoint[]
  detail_metrics?: Record<string, unknown>
  /** Optional canonical-reader metadata; additive for older imports. */
  data_as_of?: string | null
  note_synced_at?: string | null
  status?: 'ready' | 'partial' | 'unavailable' | 'stale' | string
  subject_type?: 'imported_note' | string
  scope?: 'account_history' | 'single_note' | string
  assessment_type?: 'historical_performance' | 'rqgm_content_review' | string
  algorithm_version?: string | null
  snapshot_id?: string | null
  contract_version?: string | null
}

export interface CreatorNotesQuery {
  cursor?: string | null
  limit?: number
  sort?: 'published_at_desc' | string
  published_from?: string | null
  published_to?: string | null
}

export interface CreatorNotesPayload {
  account_id: string
  items: CreatorNoteStats[]
  total: number
  limit: number
  next_cursor?: string | null
  data_as_of?: string | null
  snapshot_id?: string | null
  query?: {
    sort?: string
    published_from?: string | null
    published_to?: string | null
  }
  scope?: string
  contract_version?: string | null
  engagement_rate_unit?: 'fraction' | 'percent' | string
}

export interface CreatorAccountStats {
  account_id: string
  creator_user_id: string
  creator_name: string
  red_id: string
  avatar_url: string
  bio: string
  creator_role: string
  zone: string
  views: number
  likes: number
  comments: number
  collects: number
  shares: number
  fans: number
  note_count: number
  period: string
  synced_at: string
  snapshot_id?: string | null
  source: string
  audience_sources?: CreatorAggregatePoint[]
  audience_view_periods?: CreatorAggregatePoint[]
  audience_profile?: CreatorAggregatePoint[]
  detail_metrics?: Record<string, unknown>
}

export interface CreatorAudienceAnalysis {
  source_distribution: CreatorAggregatePoint[]
  peak_view_periods: CreatorAggregatePoint[]
  audience_profile: CreatorAggregatePoint[]
  detail_metrics?: Record<string, unknown>
  coverage: {
    sources: boolean
    periods: boolean
    profile: boolean
    notes_with_view_sources?: number
  }
  insights: string[]
}

export interface CreatorStatsSyncResult {
  account_id: string
  notes_imported: number
  notes_updated: number
  account_synced: boolean
  analysis?: {
    note_count?: number
    avg_engagement_rate?: number
    styles_deposited?: number
    findings?: unknown[]
  } | null
  suggestions?: Record<string, CreatorSuggestion[]>
  source: string
  error?: string | null
  niche_resolution?: NicheResolution | null
  ok?: boolean
  import_ok?: boolean
  analyzed?: boolean
}

export interface CreatorStatsBatchSyncResult {
  ok: boolean
  status: 'completed' | 'already_running' | 'failed' | string
  active_accounts: number
  succeeded: number
  failed: number
  results: CreatorStatsSyncResult[]
  started_at?: string
  finished_at?: string
  error?: string
}

export interface CreatorSuggestion {
  mode: string
  category: string
  title: string
  advice: string
  priority: number
  evidence: string
}

export interface CreatorStatsPayload {
  account_id: string
  account: CreatorAccountStats | null
  notes: CreatorNoteStats[]
  /** Full note count (not limited by page size) */
  total: number
  limit?: number
  fetched_at: string
  audience_analysis?: CreatorAudienceAnalysis
  data_as_of?: string | null
  snapshot_id?: string | null
  scope?: string
  subject_type?: string
  assessment_type?: string
  algorithm_version?: string | null
  status?: string
  contract_version?: string | null
  engagement_rate_unit?: 'fraction' | 'percent' | string
}

export interface CreatorSuggestionsPayload {
  account_id: string
  mode: string
  suggestions: CreatorSuggestion[]
  count: number
  cold_start: boolean
}

export type CreatorQualityDimensionKey =
  | 'engagement'
  | 'save_value'
  | 'title_craft'
  | 'consistency'

export type CreatorQualityInsightDimension = CreatorQualityDimensionKey | 'data_collection'
export type CreatorQualityGrade = 'strong' | 'developing' | 'needs_attention' | 'insufficient_data'
export type CreatorQualityConfidence = 'low' | 'medium' | 'high'
export type CreatorQualityScope =
  | 'account_history'
  | 'single_note'
  // Compatibility for older persisted/report payloads.
  | 'all_imported_history'
  | 'single_imported_note'

/** Deterministic account-level quality signal derived from imported note history. */
export interface CreatorQualityDimension {
  key: CreatorQualityDimensionKey
  score: number | null
  evidence: string
  available?: boolean
}

export interface CreatorQualityInsight {
  dimension: CreatorQualityInsightDimension
  title: string
  evidence: string
  related_note_ids: string[]
}

export interface CreatorQualityRecommendation extends CreatorQualityInsight {
  priority: number
  advice: string
}

export interface CreatorQualityReport {
  account_id: string
  note_id?: string
  /** The historical population covered by this read-only report. */
  scope: CreatorQualityScope
  total_notes: number
  notes_analyzed: number
  overall_score: number | null
  grade: CreatorQualityGrade
  confidence: CreatorQualityConfidence
  summary: string
  dimensions: CreatorQualityDimension[]
  strengths: CreatorQualityInsight[]
  weaknesses: CreatorQualityInsight[]
  recommendations: CreatorQualityRecommendation[]
  cold_start: boolean
  insufficient_data: boolean
  data_as_of?: string | null
  algorithm_version?: string | null
  status?: 'ready' | 'partial' | 'unavailable' | string
  coverage?: Record<string, unknown> | null
  snapshot_id?: string | null
  contract_version?: string | null
}

/** Import real Creator Center account/note stats through the account's bound browser. */
export async function syncCreatorStats(body: {
  account_id: string
  period?: string
  analyze?: boolean
}): Promise<CreatorStatsSyncResult> {
  return client.post(
    '/analytics/creator-stats/sync',
    {
      account_id: body.account_id,
      period: body.period ?? '30d',
      analyze: body.analyze ?? true,
    },
    // Browser-backed Creator Center capture can exceed the default 30s.
    { timeout: 120000 }
  ) as unknown as CreatorStatsSyncResult
}

/** Import real Creator Center stats for every active account. */
export async function syncAllCreatorStats(body: {
  period?: string
  analyze?: boolean
} = {}): Promise<CreatorStatsBatchSyncResult> {
  return client.post('/analytics/creator-stats/sync-all', {
    period: body.period ?? '30d',
    analyze: body.analyze ?? true,
  }, { timeout: 120000 }) as unknown as CreatorStatsBatchSyncResult
}

export async function getCreatorStats(
  accountId: string,
  limit = 50
): Promise<CreatorStatsPayload> {
  return client.get(`/analytics/creator-stats/${accountId}`, {
    params: { limit },
  }) as unknown as CreatorStatsPayload
}

/**
 * Canonical reader for imported historical notes.
 *
 * Both Analytics and Evaluation use this cursor contract.  The bounded
 * creator-stats overview remains available for legacy callers, but new UI
 * lists must not invent their own limits or offset pagination.
 */
export async function getCreatorNotes(
  accountId: string,
  query: CreatorNotesQuery = {},
  options?: { suppressToast?: boolean },
): Promise<CreatorNotesPayload> {
  // The canonical reader accepts up to 500 rows per cursor page. Keep this
  // boundary aligned with the API rather than inheriting the legacy overview
  // endpoint's 200-row cap; cursor pagination still remains the default path.
  const requestedLimit = Math.max(1, Math.min(query.limit ?? 50, 500))
  if (!QUALITY_CONSISTENCY_V2_ENABLED) {
    const legacy = await getCreatorStats(accountId, Math.min(requestedLimit, 200))
    return {
      account_id: accountId,
      items: legacy.notes || [],
      total: legacy.total ?? legacy.notes?.length ?? 0,
      limit: legacy.limit ?? Math.min(requestedLimit, 200),
      next_cursor: null,
      data_as_of: legacy.data_as_of ?? legacy.fetched_at ?? null,
      snapshot_id: legacy.snapshot_id ?? null,
      query: {
        sort: query.sort ?? 'published_at_desc',
        published_from: query.published_from ?? null,
        published_to: query.published_to ?? null,
      },
    }
  }
  const params: Record<string, string> = {
    limit: String(requestedLimit),
    sort: query.sort ?? 'published_at_desc',
  }
  if (query.cursor) params.cursor = query.cursor
  if (query.published_from) params.published_from = query.published_from
  if (query.published_to) params.published_to = query.published_to

  try {
    return await client.get(`/analytics/creator-stats/${accountId}/notes`, {
      params,
      ...(options ?? {}),
    }) as unknown as CreatorNotesPayload
  } catch (error) {
    // Additive rollout compatibility: older servers expose only the bounded
    // overview. Preserve the canonical shape while the server is upgraded;
    // callers still display the bounded/legacy nature via its total field.
    const code = String((error as { code?: unknown })?.code || '')
    if (!['NOT_FOUND', 'HTTP_404', 'NETWORK_ERROR'].includes(code) && !/fetch|network|404/i.test(String((error as Error)?.message || ''))) {
      throw error
    }
    // The compatibility endpoint still validates its historical 200-row
    // bound, so cap only the fallback request while preserving canonical
    // callers' requested page size on upgraded servers.
    const legacy = await getCreatorStats(accountId, Math.min(requestedLimit, 200))
    return {
      account_id: accountId,
      items: legacy.notes || [],
      total: legacy.total ?? legacy.notes?.length ?? 0,
      limit: legacy.limit ?? Math.min(requestedLimit, 200),
      next_cursor: null,
      data_as_of: legacy.data_as_of ?? legacy.fetched_at ?? null,
      query: {
        sort: params.sort,
        published_from: query.published_from ?? null,
        published_to: query.published_to ?? null,
      },
    }
  }
}

export interface CreatorNoteDetailPayload {
  account_id: string
  note: CreatorNoteStats
  fetched_at: string
  data_as_of?: string | null
  note_synced_at?: string | null
  scope?: string
  snapshot_id?: string | null
  contract_version?: string | null
}

export interface CreatorNoteQualityPayload {
  account_id: string
  note_id: string
  quality: CreatorQualityReport
  analyzed_at: string
  data_as_of?: string | null
  scope?: string
  status?: string
  coverage?: Record<string, unknown>
  algorithm_version?: string | null
  snapshot_id?: string | null
  contract_version?: string | null
}

/** Read one imported historical note without starting a browser sync. */
export async function getCreatorNote(
  accountId: string,
  noteId: string
): Promise<CreatorNoteDetailPayload> {
  return client.get(
    '/analytics/creator-stats/' + accountId + '/notes/' + noteId
  ) as unknown as CreatorNoteDetailPayload
}

/** Evaluate one imported historical note with the deterministic quality analyzer. */
export async function getCreatorNoteQuality(
  accountId: string,
  noteId: string,
  locale: 'zh-CN' | 'en' | string = 'zh-CN'
): Promise<CreatorNoteQualityPayload> {
  return client.get(
    '/analytics/creator-stats/' + accountId + '/notes/' + noteId + '/quality',
    { params: { locale } }
  ) as unknown as CreatorNoteQualityPayload
}

export async function getCreatorSuggestions(
  accountId: string,
  mode: string = 'trend'
): Promise<CreatorSuggestionsPayload> {
  return client.get(`/analytics/creator-stats/${accountId}/suggestions`, {
    params: { mode },
  }) as unknown as CreatorSuggestionsPayload
}

/**
 * Read the account's historical creative-quality report.
 * This endpoint is analysis-only: it never starts a Creator Center browser sync.
 */
export async function getCreatorQuality(
  accountId: string,
  locale: 'zh-CN' | 'en' | string = 'zh-CN'
): Promise<CreatorQualityReport> {
  return client.get(`/analytics/creator-stats/${accountId}/quality`, {
    params: { locale },
  }) as unknown as CreatorQualityReport
}
