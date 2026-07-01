/** RQGM agent-as-a-judge creation-quality evaluation result types. */

/** 单维度 judge 评分（agent-as-a-judge 面板的一维）. */
export interface DimensionScore {
  /** copywriting | visual | compliance | reach | audience | bias_check */
  dimension: string
  /** 0-100 */
  score: number
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
}

/** 创作质量评估结果 — RQGM agent-as-a-judge 面板输出. */
export interface EvaluationResult {
  /** 0-100 加权综合 */
  overall_score: number
  dimensions: DimensionScore[]
  /** approved / needs_revision / rejected */
  decision: string
  /** 给 copywriter 的修订指令（不合格时） */
  revision_hints: string[]
  /** 对抗偏倚检测结论（无偏倚则空串） */
  bias_warning: string
  summary: string
}

/** GET /evaluation/result/{thread_id} 响应. */
export interface EvaluationResultResponse {
  thread_id: string
  has_evaluation: boolean
  evaluation_result: EvaluationResult
}

/** 一个趋势数据点（按时序）. */
export interface TrendPoint {
  created_at: string
  overall_score: number
  decision: string
  dim_scores: Record<string, number>
}

/** GET /evaluation/trend 响应. */
export interface EvaluationTrendResponse {
  db_ready: boolean
  points: TrendPoint[]
  dim_averages: Record<string, number>
}

