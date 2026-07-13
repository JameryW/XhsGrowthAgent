import client from './client'
import type { GrowthReport, PerformanceData, CostData } from '@/types/analytics'
import type { NicheResolution } from './accounts'

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
): Promise<{ report: GrowthReport; performance: PerformanceData; costs: CostData }> {
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
  detail_metrics?: Record<string, unknown>
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
export type CreatorQualityScope = 'all_imported_history'

/** Deterministic account-level quality signal derived from imported note history. */
export interface CreatorQualityDimension {
  key: CreatorQualityDimensionKey
  score: number | null
  evidence: string
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

export async function getCreatorStats(
  accountId: string,
  limit = 50
): Promise<CreatorStatsPayload> {
  return client.get(`/analytics/creator-stats/${accountId}`, {
    params: { limit },
  }) as unknown as CreatorStatsPayload
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
