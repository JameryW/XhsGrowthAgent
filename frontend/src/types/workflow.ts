import type { ContentVersion, DraftContent, OptimizationAnalysis } from './optimization'

// Workflow phase - matches backend WorkflowPhase enum
export type WorkflowPhase =
  | 'idle'
  | 'scouting'
  | 'planning'
  | 'creating'
  | 'briefing'
  | 'reviewing'
  | 'publishing'
  | 'analyzing'
  | 'engaging'
  | 'completed'
  | 'error'
  | 'paused'
  | 'cancelled'

// Workflow status - matches backend WorkflowStatus enum
export type WorkflowStatus =
  | 'idle'
  | 'running'
  | 'stale'
  | 'awaiting_review'
  | 'awaiting_choice'
  | 'awaiting_draft'
  | 'awaiting_brief'
  | 'awaiting_ripple_decision'
  | 'awaiting_blogger_selection'
  | 'paused'
  | 'completed'
  | 'error'
  | 'cancelled'

// Content type - matches backend ContentType enum
export type ContentType =
  | 'note'
  | 'video'
  | 'carousel'

// Urgency level - matches backend Urgency enum
export type Urgency =
  | 'low'
  | 'medium'
  | 'high'
  | 'trending'

// Start request
export interface WorkflowStartRequest {
  account_id: string
  phase?: WorkflowPhase
  dry_run?: boolean
  auto_publish?: boolean
  topic?: string
  niche?: string
  execution_mode?: 'single' | 'continuous'
  workflow_mode?: 'trend' | 'brief'
  brief_text?: string
}

// Workflow list item (from /workflow/list)
export interface WorkflowListItem {
  thread_id: string
  account_id: string
  phase: WorkflowPhase
  status: WorkflowStatus
  dry_run: boolean
  auto_publish: boolean
  progress_percent: number
  workflow_mode: 'trend' | 'brief'
  label: string
  created_at: string
  updated_at: string
  error: string | null
}

// Workflow list response
export interface WorkflowListResponse {
  workflows: WorkflowListItem[]
  total: number
  limit: number
  offset: number
}

// Workflow response
export interface WorkflowResponse {
  thread_id: string
  status: WorkflowStatus
  phase: WorkflowPhase
  progress_percent?: number
  sse_url?: string
  websocket_url?: string
}

// Workflow pause result
export interface WorkflowPauseResult {
  thread_id: string
  status: 'paused'
}

// Trend data
export interface TrendData {
  hot_topics?: HotTopicItem[]
  trending_keywords?: string[]
  competitor_posts?: CompetitorPost[]
  niche_opportunities?: NicheOpportunity[]
  timestamp?: string
}

// Hot topic item
export interface HotTopicItem {
  topic: string
  heat_score: number
  heat_percentage?: number
  growth_rate?: number
  related_keywords: string[]
}

// Competitor post
export interface CompetitorPost {
  title: string
  likes: number
  comments: number
  author: string
}

// Entry barrier
export type EntryBarrier = 'low' | 'medium' | 'high'

// Niche opportunity
export interface NicheOpportunity {
  topic: string
  potential_score: number
  audience_match: string
  entry_barrier: EntryBarrier
}

// Content plan
export interface ContentPlan {
  selected_topic: string
  content_angle: string
  content_type: ContentType
  target_audience: string
  key_points: string[]
  suggested_timing: string
  hashtags: string[]
  urgency: Urgency
}

// Tone
export type Tone = 'professional' | 'friendly' | 'casual' | 'enthusiastic'

// Copy content
export interface CopyContent {
  title_candidates: string[]
  selected_title: string
  body_text: string
  hashtags: string[]
  cta: string
  emoji_usage: string[]
  tone: Tone
  raw_content?: string // Fallback for malformed JSON
}

// Visual plan
export interface VisualPlan {
  cover_prompt: string
  image_count: number
  image_prompts: string[]
  layout_style: string
  color_palette: string[]
  font_suggestion: string
  brand_elements: string[]
  image_paths?: string[]
}

// Ripple CAS prediction result
// ── Ripple CAS Engine Types ──

export interface RippleProgress {
  job_id: string
  current_wave: number
  total_waves: number
  progress: number
  elapsed_seconds: number
  status: string
  skill?: string
}

// Aggregated progress for all running Ripple jobs on a thread
export interface RippleThreadProgress {
  jobs: Record<string, RippleProgress>
  overall_progress: number
  active_jobs: number
  total_jobs: number
}

export interface RipplePrediction {
  job_id?: string
  ripple_job_id?: string
  estimated_reach?: number
  estimated_engagement?: number
  viral_probability?: number
  phase?: string
  confidence?: number
  key_influencers?: Array<Record<string, unknown>>
  spread_path?: Array<Record<string, unknown>>
  prediction_summary?: string
  verdict?: string
  relative_estimate?: Record<string, unknown>
  views_relative?: string
  engagements_relative?: string
  favorites_relative?: string
  comments_relative?: string
  shares_relative?: string
  follows_relative?: string
  phase_vector?: Record<string, unknown>
  total_waves?: number
  score_source?: string
  confidence_gate?: {
    gate_applied?: boolean
    original_confidence?: string
    final_confidence?: string
    reason?: string
    factors?: Array<{ name: string; level: string; reason: string; passed: boolean }>
  }
  quality?: Record<string, unknown>
}

// Ripple PMF validation result
export interface RipplePMFResult {
  job_id?: string
  ripple_job_id?: string
  pmf_score?: number
  risk_factors?: string[]
  improvement_strategies?: string[]
  market_segment?: Record<string, unknown>
  confidence?: number
  prediction_summary?: string
  verdict?: string
  phase?: string
  relative_estimate?: Record<string, unknown>
  views_relative?: string
  engagements_relative?: string
  favorites_relative?: string
  comments_relative?: string
  shares_relative?: string
  follows_relative?: string
  phase_vector?: Record<string, unknown>
  total_waves?: number
  score_source?: string
  confidence_gate?: {
    gate_applied?: boolean
    original_confidence?: string
    final_confidence?: string
    reason?: string
    factors?: Array<{ name: string; level: string; reason: string; passed: boolean }>
  }
  quality?: Record<string, unknown>
}

// Ripple prediction vs actual comparison
export interface RippleComparison {
  predicted_reach?: number
  actual_engagement_rate?: number
  reach_deviation?: number
  engagement_deviation?: number
  accuracy_rating?: string
  calibration_insight?: string
}

// ── Blogger reference system ──

// Blogger profile — candidate for user selection
export interface BloggerProfile {
  user_id: string
  nickname: string
  avatar_url?: string
  follower_count?: number
  note_count?: number
  total_engagement?: number
  top_note_title?: string
}

// Blogger note — top notes from selected blogger
export interface BloggerNote {
  note_id: string
  title: string
  body?: string
  hashtags?: string[]
  likes?: number
  collects?: number
  comments?: number
  engagement_rate?: number
  cover_url?: string
}

// Workflow state (matches XHSGrowthState)
export interface WorkflowState {
  thread_id: string
  phase: WorkflowPhase
  current_agent?: string
  trend_data?: TrendData
  content_plan?: ContentPlan
  copy_content?: CopyContent
  draft_content?: DraftContent
  optimization_analysis?: OptimizationAnalysis
  content_versions?: ContentVersion[]
  visual_plan?: VisualPlan
  ripple_prediction?: RipplePrediction
  ripple_pmf?: RipplePMFResult
  ripple_comparison?: RippleComparison
  error?: string | null
  created_at: string
  updated_at: string
}

// Agent timeline entry (per-agent execution detail)
export interface AgentTimelineEntry {
  agent: string
  started_at: string
  completed_at: string
  duration_seconds: number
  status: 'success' | 'error'
  error?: string | null
}

// Workflow state response (matches backend WorkflowStatusResponse)
export interface WorkflowStateResponse {
  thread_id: string
  phase: WorkflowPhase
  status: WorkflowStatus
  current_agent?: string
  next_steps: string[]
  error?: string | null
  progress_percent: number
  created_at?: string
  updated_at?: string
  agent_timeline: AgentTimelineEntry[]
  workflow_mode?: 'trend' | 'brief'
  brief_content?: BriefContent
  brief_clarification?: BriefClarification
  shooting_plan?: ShootingPlan
  trend_data?: TrendData
  content_plan?: ContentPlan
  copy_content?: CopyContent
  draft_content?: DraftContent
  optimization_analysis?: OptimizationAnalysis
  content_versions?: ContentVersion[]
  visual_plan?: VisualPlan
  publish_result?: Record<string, unknown>
  analytics?: Record<string, unknown>
  ripple_prediction?: RipplePrediction
  ripple_pmf?: RipplePMFResult
  ripple_comparison?: RippleComparison
  ripple_progress?: RippleThreadProgress
  ripple_reason?: string  // "disabled" | "unreachable" | ""
  reselect_count?: number
  label?: string
  checkpoint_lost?: boolean
  blogger_candidates?: BloggerProfile[]
  selected_blogger?: Record<string, unknown>
  blogger_notes?: BloggerNote[]
  blogger_candidate_limit?: number
  blogger_note_limit?: number
}

// Brief content - parsed from brief text/PDF
export interface BriefContent {
  raw_text?: string
  source_type?: string
  brand_name?: string
  product_name?: string
  product_specs?: string[]
  selling_points?: string[]
  required_keywords?: string[]
  required_hashtags?: string[]
  optional_hashtags?: string[]
  content_direction?: string
  target_audience?: string
  style_requirements?: string
  shooting_requirements?: string
  notes?: string[]
  confidence?: number
}

// Brief clarification - when brief is vague
export interface BriefClarification {
  questions?: Array<{
    field: string
    question: string
    options?: string[]
    inferred_value?: string
  }>
  resolved?: boolean
}

// Shooting plan - generated from brief
export interface ShootingPlan {
  creator_nickname?: string
  content_direction?: string
  content_type_label?: string
  profile_link?: string
  creator_level?: string
  planned_publish_date?: string
  product_specification?: string
  draft_requirements?: string[]
  draft_notes?: string[]
  title_candidates?: string[]
  body_copy?: string
  required_hashtags?: string[]
  optional_hashtags?: string[]
  suggested_hashtags?: string[]
  outfits?: Record<string, string[]>
  shooting_angles?: Array<{
    angle: string
    description: string
    tips?: string
  }>
}

// ── Checkpoint history (replay) ──

export interface CheckpointSnapshot {
  checkpoint_id: string
  step: number
  source: string
  phase: WorkflowPhase
  current_agent: string
  created_at: string | null
  next_nodes: string[]
  trend_data: TrendData
  content_plan: ContentPlan
  copy_content: CopyContent
  draft_content: DraftContent
  optimization_analysis: OptimizationAnalysis
  content_versions: ContentVersion[]
  visual_plan: VisualPlan
  publish_result: Record<string, unknown>
  analytics: Record<string, unknown>
  ripple_prediction: RipplePrediction
  ripple_pmf: RipplePMFResult
  ripple_comparison: RippleComparison
  workflow_mode: 'trend' | 'brief'
  brief_content: BriefContent
  shooting_plan: ShootingPlan
}

export interface CheckpointHistoryResponse {
  thread_id: string
  checkpoints: CheckpointSnapshot[]
  has_more: boolean
}
