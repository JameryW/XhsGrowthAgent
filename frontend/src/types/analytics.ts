// 增长报告
export interface GrowthReport {
  account_id: string
  period: 'daily' | 'weekly' | 'monthly'
  report: string
}

// 帖子表现
export interface PostPerformance {
  title: string
  likes: number
  comments: number
  collects: number
  engagement_rate: number
  published_at: string
}

// 性能数据
export interface PerformanceData {
  account_id: string
  posts: PostPerformance[]
}

// 成本数据
export interface CostData {
  total_cost_usd: number
  today_cost_usd: number
  circuit_open: boolean
}