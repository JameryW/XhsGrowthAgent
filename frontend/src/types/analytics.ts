// 增长报告
export interface GrowthReport {
  account_id: string
  period: 'daily' | 'weekly' | 'monthly'
  report?: string
  metrics?: {
    total_posts: number
    total_engagement: number
    avg_engagement_rate: number
    best_post_title: string
    trend_topics: string[]
  }
  insights?: Array<{
    type: 'trend' | 'opportunity' | 'warning' | 'info'
    message: string
  }>
  generated_at?: string
}

// 帖子表现
export interface PostPerformance {
  /** Workflow publish id or imported creator-center note id. */
  id?: string
  title: string
  likes: number
  comments: number
  collects: number
  shares: number
  views: number
  engagement_rate: number
  published_at: string
  /** Source of the row; imported rows are eligible for note-quality drill-down. */
  source?: string
  account_id?: string
  workflow_thread_id?: string
  platform_post_id?: string
  link_status?: 'linked' | 'unmatched' | 'ambiguous' | string
  linked_note_id?: string
}

// 性能数据
export interface PerformanceData {
  account_id: string
  posts: PostPerformance[]
  /** Number of all posts in the selected period, independent of page limit. */
  total?: number
}

export interface AnalyticsPeriodMetrics {
  posts: number
  views: number
  likes: number
  comments: number
  collects: number
  shares: number
  engagement: number
  avg_engagement_rate: number
}

export interface AnalyticsPeriodSummary {
  period: 'daily' | 'weekly' | 'monthly'
  current: AnalyticsPeriodMetrics
  previous: AnalyticsPeriodMetrics
}

// 成本数据
export interface CostData {
  total_cost_usd: number
  today_cost_usd: number
  budget_remaining_usd?: number
  by_model?: Record<string, number>
  circuit_open: boolean
}
