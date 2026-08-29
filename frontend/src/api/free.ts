import client from './client'

export type FreeDraftStatus =
  | 'all'
  | 'published'
  | 'unpublished'
  | 'publish_failed'
  | 'evaluated'
  | 'unevaluated'

export type FreeDraftRequestOptions = {
  suppressToast?: boolean
  signal?: AbortSignal
}

export interface FreeDraftEvaluation {
  overall_score?: number | null
  decision?: string | null
  revision_hints?: string[]
  degraded?: boolean
  summary?: string | null
}

/** Persisted post-publish engagement snapshot (`last_analytics`, server-set).
 *  `engagement_rate` is the display-scale value as returned by XHSAnalytics
 *  (rendered as %); fraction-typed consumers recompute from raw counts. */
export interface FreeDraftAnalytics {
  post_id?: string
  views?: number
  likes?: number
  collects?: number
  comments?: number
  shares?: number
  engagement_rate?: number
  fetched_at?: string
}

export interface FreeDraftTrend {
  views: number
  delta_views: number
  captured_at?: string | null
}

export interface FreeDraftPublishSummary {
  status?: string
  error_type?: string | null
  at?: string | null
}

export interface FreeDraftPublishAttempt extends FreeDraftPublishSummary {
  error?: string | null
}

export interface FreeDraftSummary {
  draft_id: string
  title: string
  hashtags: string[]
  created_at?: string | null
  updated_at?: string | null
  last_evaluation?: FreeDraftEvaluation | null
  /** Safe publish-attempt metadata returned by the list endpoint. */
  last_publish?: FreeDraftPublishSummary | null
  published?: boolean | null
  /** Real or mock post id when the list payload exposes publish identity. */
  post_id?: string
  last_analytics?: FreeDraftAnalytics | null
  /** Server-computed views movement between the last two captures (task
   *  08-26-free-snapshot-trend); null before two snapshots exist. */
  engagement_trend?: FreeDraftTrend | null
  /** Creative-memory anchors (task 08-26-free-anchor-display): what the draft
   *  was built on; empty string/array = not anchored. */
  style_id?: string
  play_id?: string
  material_ids?: string[]
}

export interface FreeDraftListResponse {
  account_id: string
  drafts: FreeDraftSummary[]
  count: number
  truncated?: boolean
  status?: FreeDraftStatus
  q?: string
}

export interface FreeDraftRecord extends FreeDraftSummary {
  account_id?: string
  body?: string
  image_paths?: string[]
  niche?: string
  content_angle?: string
  target_audience?: string
  last_publish?: FreeDraftPublishAttempt | null
  post_id?: string
  post_url?: string
}

export interface FreeDraftDetailResponse {
  draft_id: string
  draft: FreeDraftRecord
}

export async function listFreeDrafts(
  accountId: string,
  params: { status?: FreeDraftStatus; q?: string } = {},
  options: FreeDraftRequestOptions = {},
): Promise<FreeDraftListResponse> {
  return client.get(`/free/drafts/${encodeURIComponent(accountId)}`, {
    params,
    ...options,
  }) as unknown as FreeDraftListResponse
}

export async function getFreeDraft(
  accountId: string,
  draftId: string,
  options: FreeDraftRequestOptions = {},
): Promise<FreeDraftDetailResponse> {
  return client.get(`/free/draft/${encodeURIComponent(draftId)}`, {
    params: { account_id: accountId },
    ...options,
  }) as unknown as FreeDraftDetailResponse
}

export async function deleteFreeDraft(
  accountId: string,
  draftId: string,
  options: FreeDraftRequestOptions = {},
): Promise<{ draft_id: string; deleted: boolean }> {
  return client.delete(`/free/draft/${encodeURIComponent(draftId)}`, {
    params: { account_id: accountId },
    ...options,
  }) as unknown as { draft_id: string; deleted: boolean }
}
