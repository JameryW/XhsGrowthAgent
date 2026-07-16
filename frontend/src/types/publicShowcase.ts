export type PublicCaseStatus = 'completed' | 'in_progress' | 'attention'
export type PublicWorkflowMode = 'trend' | 'brief'
export type PublicReplayView = 'key' | 'all'

export interface PublicVisualResult {
  layout?: string
  image_count?: number
  palette?: string[]
}

export interface PublicPublishResult {
  status?: 'published' | 'scheduled' | 'draft'
  published_at?: string
  post_url?: string
}

export interface PublicMetrics {
  views?: number
  likes?: number
  collects?: number
  comments?: number
  shares?: number
  engagement_rate?: number
}

export interface PublicPrediction {
  estimated_reach?: number
  estimated_engagement?: number
  viral_probability?: number
  confidence?: number
  pmf_score?: number
  verdict?: string
}

export interface PublicResult {
  title?: string
  topic?: string
  summary?: string
  hashtags?: string[]
  key_points?: string[]
  target_audience?: string
  visual?: PublicVisualResult
  publish?: PublicPublishResult
  metrics?: PublicMetrics
  prediction?: PublicPrediction
}

export interface PublicCase {
  public_id: string
  title: string
  summary: string
  status: PublicCaseStatus
  phase: string
  workflow_mode: PublicWorkflowMode
  created_at: string
  updated_at: string
  featured: boolean
  replay_available: boolean
  result_preview: PublicResult
  result?: PublicResult
}

export interface PublicCaseListResponse {
  cases: PublicCase[]
  total: number
  limit: number
  offset: number
  featured_public_id: string | null
}

export interface PublicReplayStep {
  public_id: string
  step: number
  phase: string
  title?: string
  summary: string
  created_at: string | null
  has_result: boolean
  result_kind: string
  result?: PublicResult
  technical?: {
    phase: string
    step: number
    has_next: boolean
  }
}

export interface PublicReplayManifestResponse {
  public_id: string
  view: PublicReplayView
  steps: PublicReplayStep[]
  has_more: boolean
  technical_steps_available: boolean
  workflow: PublicCase
}

export interface PublicFinalSummaryResponse {
  public_id: string
  status: PublicCaseStatus
  result: PublicResult
  stable: boolean
}
