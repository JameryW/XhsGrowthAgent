// 工作流阶段
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

// 启动请求
export interface WorkflowStartRequest {
  account_id: string
  phase: WorkflowPhase
}

// 工作流响应
export interface WorkflowResponse {
  thread_id: string
  status: 'running' | 'paused' | 'completed' | 'error'
  phase: WorkflowPhase
}

// 工作流状态
export interface WorkflowState {
  thread_id: string
  next: string[]
  values: {
    phase: WorkflowPhase
    current_agent: string
    trend_data?: Record<string, any>
    content_plan?: Record<string, any>
    copy_content?: Record<string, any>
    visual_plan?: Record<string, any>
    created_at?: string
    updated_at?: string
    error?: string | null
  }
  created_at?: string
}