// Content status - matches backend ContentStatus enum
export type ContentStatus =
  | 'approved'
  | 'needs_revision'
  | 'rejected'
  | 'draft'
  | 'pending_review'
  | 'published'
  | 'failed'

// Review decision - subset of ContentStatus used for review decisions
export type ReviewDecision = 'approved' | 'needs_revision' | 'rejected'

// Review status indicator
export type ReviewStatus = 'awaiting_review' | 'no_pending_review'

// Revision suggestion
export interface Revision {
  field: string
  suggestion: string
}

// Import related types
import type { ContentPlan, CopyContent, VisualPlan } from './workflow'
import type { ContentVersion } from './optimization'

// Re-export for convenience
export type { ContentVersion }

// Pending review content
export interface PendingReview {
  status: ReviewStatus
  content_plan?: ContentPlan
  copy_content?: CopyContent
  visual_plan?: VisualPlan
  version_history?: ContentVersion[]
}

// Version history response
export interface VersionHistoryResponse {
  thread_id: string
  versions: ContentVersion[]
  current: {
    title: string
    body: string
    hashtags: string[]
  }
}

// Publish options for approved decisions
export interface PublishOptions {
  dry_run: boolean
  auto_publish?: boolean
}

// Review decision request
export interface ReviewDecisionRequest {
  decision: ReviewDecision
  comments?: string
  revisions?: Revision[]
  publish_options?: PublishOptions
}

// Review submit response
export interface ReviewSubmitResponse {
  thread_id: string
  status: 'resumed'
  decision: ReviewDecision
  next_phase: string
}
