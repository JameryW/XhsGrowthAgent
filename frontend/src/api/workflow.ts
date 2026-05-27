import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowStateResponse } from '@/types/workflow'

// 启动工作流
export async function startWorkflow(req: WorkflowStartRequest): Promise<WorkflowResponse> {
  return client.post('/workflow/start', req)
}

// 获取工作流状态
export async function getWorkflowStatus(threadId: string): Promise<WorkflowStateResponse> {
  return client.get(`/workflow/status/${threadId}`)
}

// 暂停工作流
export async function pauseWorkflow(threadId: string): Promise<{ thread_id: string; status: string }> {
  return client.post(`/workflow/pause/${threadId}`)
}

// 恢复工作流
export async function resumeWorkflow(threadId: string): Promise<WorkflowResponse> {
  return client.post(`/workflow/resume/${threadId}`)
}

// 取消工作流
export async function cancelWorkflow(threadId: string): Promise<{ thread_id: string; status: string; message: string }> {
  return client.post(`/workflow/cancel/${threadId}`)
}