// 内容状态
export type ContentStatus = 'approved' | 'needs_revision' | 'rejected'

// 待审核内容
export interface PendingReview {
  status: 'awaiting_review' | 'no_pending_review'
  content_plan?: Record<string, any>
  copy_content?: Record<string, any>
  visual_plan?: Record<string, any>
}

// 审核决定
export interface ReviewDecision {
  decision: ContentStatus
  comments?: string
  revisions?: string[]
}

// 审核提交响应
export interface ReviewSubmitResponse {
  thread_id: string
  status: 'resumed'
  decision: ContentStatus
  next_phase: string
}