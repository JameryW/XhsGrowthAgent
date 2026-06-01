// Workflow phase - matches backend WorkflowPhase enum
export type WorkflowPhase =
  | 'idle'
  | 'scouting'
  | 'planning'
  | 'creating'
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
  | 'running'
  | 'awaiting_review'
  | 'awaiting_choice'
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
}

// Workflow list item (from /workflow/list)
export interface WorkflowListItem {
  thread_id: string
  account_id: string
  phase: WorkflowPhase
  status: 'running' | 'completed' | 'error' | 'cancelled'
  dry_run: boolean
  auto_publish: boolean
  progress_percent: number
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
}

// Ripple CAS prediction result
export interface RipplePrediction {
  job_id?: string
  estimated_reach?: number
  estimated_engagement?: number
  viral_probability?: number
  phase?: string
  confidence?: number
  key_influencers?: Array<Record<string, unknown>>
  spread_path?: Array<Record<string, unknown>>
}

// Ripple PMF validation result
export interface RipplePMFResult {
  job_id?: string
  pmf_score?: number
  risk_factors?: string[]
  improvement_strategies?: string[]
  market_segment?: Record<string, unknown>
  confidence?: number
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

// Workflow state
export interface WorkflowState {
  thread_id: string
  phase: WorkflowPhase
  current_agent?: string
  trend_data?: TrendData
  content_plan?: ContentPlan
  copy_content?: CopyContent
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
  trend_data?: TrendData
  content_plan?: ContentPlan
  copy_content?: CopyContent
  visual_plan?: VisualPlan
  publish_result?: Record<string, unknown>
  analytics?: Record<string, unknown>
  ripple_prediction?: RipplePrediction
  ripple_pmf?: RipplePMFResult
  ripple_comparison?: RippleComparison
  ripple_reason?: string  // "disabled" | "unreachable" | ""
}