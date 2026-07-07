/** API response types matching backend/api/routes/workflow.py */

export interface WorkflowStartResponse {
  thread_id: string;
  status: string;
  phase: string;
  progress_percent?: number;
  sse_url?: string;
  websocket_url?: string;
}

export interface WorkflowStatusResponse {
  thread_id: string;
  phase: string;
  status: string;
  current_agent: string;
  next_steps: string[];
  error: string | null;
  progress_percent: number;
  created_at: string | null;
  updated_at: string | null;
  agent_timeline: AgentTimelineEntry[];
  trend_data: Record<string, unknown>;
  content_plan: Record<string, unknown>;
  copy_content: Record<string, unknown>;
  draft_content: Record<string, unknown>;
  optimization_analysis: Record<string, unknown>;
  content_versions: Record<string, unknown>[];
  visual_plan: Record<string, unknown>;
  publish_result: Record<string, unknown>;
  analytics: Record<string, unknown>;
  ripple_prediction: Record<string, unknown>;
  ripple_pmf: Record<string, unknown>;
  workflow_mode: string;
  brief_content: Record<string, unknown>;
  shooting_plan: Record<string, unknown>;
  blogger_candidates: Record<string, unknown>[];
  selected_blogger: Record<string, unknown>;
  label: string;
}

export interface AgentTimelineEntry {
  agent: string;
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  status: string;
  error: string | null;
}

export interface ReviewResponse {
  thread_id: string;
  status: string;
  decision: string;
  next_phase: string;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
}

/** Tool result content helper */
export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  details?: Record<string, unknown>;
  isError?: boolean;
}

/** Create a text tool result */
export function textResult(text: string, details?: Record<string, unknown>, isError = false): ToolResult {
  return { content: [{ type: "text", text }], ...(details && { details }), ...(isError && { isError }) };
}
