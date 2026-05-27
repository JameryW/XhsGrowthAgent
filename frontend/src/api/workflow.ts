import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowStateResponse } from '@/types/workflow'
import { useRetry } from '@/composables/useRetry'

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

// 获取工作流状态
export async function getWorkflowStatus(threadId: string): Promise<WorkflowStateResponse> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.get(`/workflow/status/${threadId}`) as WorkflowStateResponse
      return result
    } catch (error) {
      throw error
    }
  })
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