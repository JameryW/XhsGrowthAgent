import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowStateResponse, WorkflowListResponse, CheckpointHistoryResponse } from '@/types/workflow'
import { useRetry } from '@/composables/useRetry'

// Brief upload result from backend
export interface BriefUploadResult {
  thread_id: string
  brief_text: string
  source_type: string
}

// 工作流列表
export async function listWorkflows(params?: {
  account_id?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<WorkflowListResponse> {
  return client.get('/workflow/list', { params }) as unknown as WorkflowListResponse
}

// 启动工作流
export async function startWorkflow(req: WorkflowStartRequest): Promise<WorkflowResponse> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.post('/workflow/start', req) as WorkflowResponse
      return result
    } catch (error) {
      throw error
    }
  })
}

// 获取工作流状态（不重试，404 是正常场景）
export async function getWorkflowStatus(threadId: string): Promise<WorkflowStateResponse> {
  return client.get(`/workflow/status/${threadId}`) as unknown as WorkflowStateResponse
}

// 暂停工作流
export async function pauseWorkflow(threadId: string): Promise<{ thread_id: string; status: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.post(`/workflow/pause/${threadId}`) as { thread_id: string; status: string }
      return result
    } catch (error) {
      throw error
    }
  })
}

// 恢复工作流
export async function resumeWorkflow(threadId: string, resumeValue?: Record<string, unknown>): Promise<WorkflowResponse> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const payload = resumeValue ? { resume_value: resumeValue } : undefined
      const result = await client.post(`/workflow/resume/${threadId}`, payload) as WorkflowResponse
      return result
    } catch (error) {
      throw error
    }
  })
}

// 取消工作流
export async function cancelWorkflow(threadId: string): Promise<{ thread_id: string; status: string; message: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.post(`/workflow/cancel/${threadId}`) as { thread_id: string; status: string; message: string }
      return result
    } catch (error) {
      throw error
    }
  })
}

// 删除工作流历史记录
export async function deleteWorkflow(threadId: string): Promise<{ thread_id: string; message: string }> {
  return client.delete(`/workflow/${threadId}`) as unknown as { thread_id: string; message: string }
}

// 重试 Ripple 分析
export async function retryRippleAnalysis(threadId: string): Promise<{ thread_id: string; status: string; message: string }> {
  return client.post(`/workflow/ripple-retry/${threadId}`) as unknown as { thread_id: string; status: string; message: string }
}

// 提交 Ripple 决策（接受/换角度/换话题）
export async function submitRippleDecision(threadId: string, action: 'accept' | 'reangle' | 'retopic'): Promise<{ thread_id: string; status: string; action: string; next_phase: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    const result = await client.post(`/review/ripple-decision/${threadId}`, { action }) as { thread_id: string; status: string; action: string; next_phase: string }
    return result
  })
}

// 获取 Ripple 决策等待状态
export async function getPendingRippleDecision(threadId: string): Promise<{
  status: string
  ripple_prediction: Record<string, unknown>
  ripple_pmf: Record<string, unknown>
  reselect_count: number
  max_reselect: number
  options: string[]
}> {
  return client.get(`/review/ripple-pending/${threadId}`) as unknown as any
}

// 提交草稿到优化流程
export async function submitDraft(threadId: string, data: {
  title?: string
  text: string
  hashtags?: string[]
  viral_links?: string[]
}): Promise<{ thread_id: string; status: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    const result = await client.post(`/optimization/draft/${threadId}`, data) as { thread_id: string; status: string }
    return result
  })
}

// 选择优化版本
export async function selectVersion(threadId: string, choice: {
  version_id: string
  version_type?: string
}): Promise<{ thread_id: string; status: string; next_phase: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    const result = await client.post(`/optimization/select/${threadId}`, choice) as { thread_id: string; status: string; next_phase: string }
    return result
  })
}

// Extract brief text from PDF without requiring a thread ID
export async function extractBriefFile(file: File): Promise<{ brief_text: string; source_type: string }> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`/api/workflow/brief/extract`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const msg = body?.error?.message || body?.detail || `Extraction failed: ${res.status}`
    throw new Error(msg)
  }

  const json = await res.json()
  return json.data as { brief_text: string; source_type: string }
}

// Upload brief PDF file — uses FormData, can't go through axios JSON interceptor
export async function uploadBriefFile(threadId: string, file: File): Promise<BriefUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`/api/workflow/brief/upload/${threadId}`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const msg = body?.error?.message || body?.detail || `Upload failed: ${res.status}`
    throw new Error(msg)
  }

  const json = await res.json()
  // Backend wraps in ApiResponse: { success, data: {...} }
  return json.data as BriefUploadResult
}

// Get checkpoint history for replay
export async function getCheckpointHistory(threadId: string, params?: {
  limit?: number
  before?: string
}): Promise<CheckpointHistoryResponse> {
  return client.get(`/workflow/history/${threadId}`, { params }) as unknown as CheckpointHistoryResponse
}

// Select a blogger from candidates — resume blogger_gate
export async function selectBlogger(threadId: string, selection: {
  user_id: string
  nickname: string
} | { skip: true }): Promise<{ thread_id: string; status: string; next_phase?: string }> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    const result = await client.post(`/optimization/blogger-select/${threadId}`, selection) as { thread_id: string; status: string; next_phase?: string }
    return result
  })
}

// Get pending blogger selection — candidate list and config
export async function getPendingBloggerSelection(threadId: string): Promise<{
  thread_id: string
  blogger_candidates: Array<Record<string, unknown>>
  blogger_candidate_limit: number
  blogger_note_limit: number
  is_pending: boolean
}> {
  return client.get(`/optimization/blogger-pending/${threadId}`) as unknown as any
}