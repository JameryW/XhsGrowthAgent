import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowStateResponse, WorkflowListResponse } from '@/types/workflow'
import { useRetry } from '@/composables/useRetry'

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
export async function resumeWorkflow(threadId: string): Promise<WorkflowResponse> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.post(`/workflow/resume/${threadId}`) as WorkflowResponse
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