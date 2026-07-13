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
}

export interface CreatorSuggestionsPayload {
  account_id: string
  mode: string
  suggestions: CreatorSuggestion[]
  count: number
  cold_start: boolean
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
