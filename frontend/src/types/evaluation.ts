/** RQGM agent-as-a-judge creation-quality evaluation result types. */
import type { ScoreThresholds } from '@/constants/evaluation'

/** 单维度 judge 评分（agent-as-a-judge 面板的一维）. */
export interface DimensionScore {
  /** copywriting | visual | compliance | reach | audience | ai_taste | image_quality | commercial_tone | altruism | bias_check */
  dimension: string
  /** 0-100 */
  score: number | null
  /**
   * bias_check 维度专属：检测到的偏倚严重度（0-100，越高越糟）。
   * 与 score（"校准建议分"）语义相反，独立产出。旧样本可能缺省。
   */
  bias_severity?: number
  /** 该维度评分理由 */
  rationale: string
  /** 发现的具体问题 */
  issues: string[]
  /** True = 硬性失败（如合规），无论总分都判不合格 */
  is_blocking: boolean
  /** Whether this dimension had enough input to be scored. */
  available?: boolean
  /** Optional reason when the dimension could not be scored. */
  unavailable_reason?: string | null
}

/** 创作质量评估结果 — RQGM agent-as-a-judge 面板输出. */
export interface EvaluationResult {
  /** 0-100 加权综合 */
  overall_score: number | null
  dimensions: DimensionScore[]
  /** approved / needs_revision / rejected */
  decision: string | null
  /** 给 copywriter 的修订指令（不合格时） */
  revision_hints: string[]
  /** 对抗偏倚检测结论（无偏倚则空串） */
  bias_warning: string
  summary: string
  /** Additive evaluation lifecycle state. */
  status?: EvaluationStatus
  /** Legacy backend compatibility marker for timeout/fallback responses. */
  degraded?: boolean
  coverage?: EvaluationCoverage
  evaluated_at?: string
  evaluation_id?: string
  evaluator_fingerprint?: string
}

export type EvaluationStatus =
  | 'ready'
  | 'partial'
  | 'unavailable'
  | 'running'
  | 'degraded'
  | 'failed'
  | string

export interface EvaluationCoverage {
  weighted_ratio?: number | null
  available_dimensions?: string[]
  unavailable_dimensions?: string[]
  [key: string]: unknown
}

/** GET /evaluation/result/{thread_id} 响应. */
export interface EvaluationResultResponse {
  thread_id: string
  has_evaluation: boolean
  evaluation_result: EvaluationResult
  /** Effective per-account score bands used by the evaluator. */
  thresholds?: ScoreThresholds
  account_id?: string
  scope?: string
  assessment_type?: 'rqgm_content_review' | string
  status?: EvaluationStatus
  degraded?: boolean
  coverage?: EvaluationCoverage
  data_as_of?: string | null
  evaluated_at?: string | null
  evaluation_id?: string | null
  evaluator_fingerprint?: string | null
}


/** 一个趋势数据点（按时序）. */
export interface TrendPoint {
  created_at: string
  overall_score: number | null
  decision: string | null
  dim_scores: Record<string, number>
  status?: EvaluationStatus
  degraded?: boolean
  account_id?: string
  assessment_type?: 'rqgm_content_review' | string
  evaluated_at?: string
}

/** GET /evaluation/list 单条 — 有评估结果的工作流摘要. */
export interface EvaluationListItem {
  thread_id: string
  account_id: string
  status: string
  phase: string
  label: string
  workflow_mode: string
  updated_at: string
  created_at?: string
  /** state.copy_content.selected_title — 列表标题展示用 */
  selected_title: string
  /** 0-100 综合分预览 */
  overall_score: number | null
  /** approved / needs_revision / rejected */
  decision: string | null
  pass_threshold?: number
  warn_threshold?: number
  scope?: string
  assessment_type?: 'rqgm_content_review' | string
  status_detail?: EvaluationStatus
  degraded?: boolean
  data_as_of?: string | null
  evaluated_at?: string | null
  evaluation_id?: string | null
  evaluator_fingerprint?: string | null
}

/** GET /evaluation/list 响应. */
export interface EvaluationListResponse {
  workflows: EvaluationListItem[]
  total: number
  limit: number
  offset: number
  account_id?: string | null
  scope?: string
  data_as_of?: string | null
}

/** GET /evaluation/trend 响应. */
export interface EvaluationTrendResponse {
  db_ready: boolean
  points: TrendPoint[]
  dim_averages: Record<string, number>
  account_id?: string | null
  scope?: string
  assessment_type?: 'rqgm_content_review' | string
  data_as_of?: string | null
  pass_threshold?: number
  warn_threshold?: number
}
