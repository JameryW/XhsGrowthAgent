// ── 发布前优化系统类型 ──

// 用户原始草稿
export interface DraftContent {
  text: string
  images?: string[]
  title?: string
  hashtags?: string[]
  provided_at?: string
}

// 爆款参考笔记
export interface ViralPost {
  note_id: string
  title: string
  body: string
  hashtags: string[]
  cover_url: string
  image_urls?: string[]
  likes: number
  collects: number
  comments: number
  engagement_rate: number
  visual_style: string
  color_palette?: Record<string, string>
}

// 差距项
export interface GapItem {
  dimension: string
  description: string
  severity: 'low' | 'medium' | 'high'
}

// 优化建议项
export interface SuggestionItem {
  dimension: string
  action: string
  reasoning: string
  priority: number
}

// 优化分析报告
export interface OptimizationAnalysis {
  gaps: GapItem[]
  suggestions: SuggestionItem[]
  viral_patterns: string[]
}

// 内容版本
export interface ContentVersion {
  version_id: string
  version_type?: 'A' | 'B' | 'C'
  title: string
  body: string
  hashtags: string[]
  image_prompts?: string[]
  style_suggestion?: string
  changes_summary: string
  predicted_score: number
  created_at?: string
}

// 版本选择结果
export interface VersionChoice {
  selected_version: 'A' | 'B' | 'C'
  version_id: string
}

// ── API 请求/响应类型 ──

// 提交草稿请求
export interface SubmitDraftRequest {
  thread_id: string
  draft: DraftContent
  viral_links?: string[]
}

// 提交草稿响应
export interface SubmitDraftResponse {
  thread_id: string
  phase: WorkflowPhase
  viral_posts?: ViralPost[]
}

// 版本选择请求
export interface SelectVersionRequest {
  thread_id: string
  choice: VersionChoice
}

// 版本选择响应
export interface SelectVersionResponse {
  thread_id: string
  phase: WorkflowPhase
  copy_content?: CopyContent
  visual_plan?: VisualPlan
}

// 导入依赖类型
import type { WorkflowPhase } from './workflow'
import type { CopyContent, VisualPlan } from './workflow'