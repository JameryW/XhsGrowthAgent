// frontend/src/realtime/events.ts

/** 事件类型枚举 - 与后端backend.realtime.events.EventType同步 */

export enum EventType {
  // Workflow
  WORKFLOW_STARTED = "workflow.started",
  WORKFLOW_PHASE_CHANGED = "workflow.phase_changed",
  WORKFLOW_AGENT_STARTED = "workflow.agent_started",
  WORKFLOW_AGENT_COMPLETED = "workflow.agent_completed",
  WORKFLOW_DATA_UPDATED = "workflow.data_updated",
  WORKFLOW_PAUSED = "workflow.paused",
  WORKFLOW_RESUMED = "workflow.resumed",
  WORKFLOW_COMPLETED = "workflow.completed",
  WORKFLOW_ERROR = "workflow.error",

  // Ripple CAS engine
  RIPPLE_PROGRESS = "ripple.progress",

  // Review
  REVIEW_PENDING = "review.pending",
  REVIEW_SUBMITTED = "review.submitted",
  REVIEW_APPROVED = "review.approved",
  REVIEW_REJECTED = "review.rejected",
  REVIEW_NEEDS_REVISION = "review.needs_revision",

  // Analytics
  ANALYTICS_REPORT_UPDATED = "analytics.report_updated",
  ANALYTICS_COST_ALERT = "analytics.cost_alert",
  ANALYTICS_PERFORMANCE_NEW = "analytics.performance_new",

  // Evaluator (RQGM) self-evolution — refit weights / advance prompt epoch
  EVALUATOR_EPOCH_EVOLVED = "evaluator.epoch_evolved",
}

/** WebSocket连接状态 */
export type WsStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

/** 服务端推送消息格式 */
export interface WsMessage {
  event_type: EventType
  thread_id: string | null
  payload: unknown
  timestamp: string
  seq: number
}

/** 客户端发送消息格式 */
export interface WsClientMessage {
  action: "subscribe" | "unsubscribe" | "ping" | "get_missed"
  thread_id?: string
  since?: number
}

/** 补传事件响应 */
export interface WsMissedEventsResponse {
  action: "missed_events"
  events: WsMessage[]
}