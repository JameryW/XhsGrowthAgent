import client from './client'
import type {
  EvaluationListResponse,
  EvaluationResultResponse,
  EvaluationTrendResponse,
} from '@/types/evaluation'
import { ALL_ACCOUNTS_ID } from '@/constants/qualityConsistency'

type RequestOptions = { suppressToast?: boolean }

interface EvaluationSourceMetadata {
  content_hash?: string | null
  data_as_of?: string | null
  context_hash?: string | null
  niche?: string | null
  niche_source?: string | null
  note_synced_at?: string | null
  snapshot_id?: string | null
}

// 列出有评估结果的工作流 — 含标题 + 评估摘要（专用端点，不污染通用 /workflow/list）
export async function getEvaluationList(
  accountId?: string,
  limit = 20,
  offset = 0,
  options?: RequestOptions,
): Promise<EvaluationListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (accountId && accountId !== ALL_ACCOUNTS_ID) params.set('account_id', accountId)
  return client.get(`/evaluation/list?${params.toString()}`, options) as unknown as EvaluationListResponse
}

// 获取指定工作流的创作质量评估结果（RQGM agent-as-a-judge）
export async function getEvaluationResult(threadId: string, options?: RequestOptions): Promise<EvaluationResultResponse> {
  return client.get(`/evaluation/result/${threadId}`, options) as unknown as EvaluationResultResponse
}

// RQGM note evaluation can take 60–120s (10-dim LLM panel + retries).
// Default axios timeout is 30s and surfaces as "Request timeout".
const EVALUATE_NOTE_TIMEOUT_MS = 180_000

// 对已导入历史笔记手动触发 RQGM 评估（thread-less，不写 checkpoint）
export async function evaluateNote(
  accountId: string,
  noteId: string,
  options?: RequestOptions & { force?: boolean },
): Promise<{
  account_id: string
  note_id: string
  evaluation_result: EvaluationResultResponse['evaluation_result']
  thresholds?: EvaluationResultResponse['thresholds']
  evaluation_id?: string | null
  status?: EvaluationResultResponse['status']
  degraded?: boolean
  coverage?: EvaluationResultResponse['coverage']
  data_as_of?: string | null
  source?: EvaluationSourceMetadata
  evaluated_at?: string | null
  evaluator_fingerprint?: string | null
  stale?: boolean
  stale_at?: string | null
  cache_hit?: boolean
  snapshot_id?: string | null
  contract_version?: string | null
}> {
  const body: Record<string, unknown> = { account_id: accountId, note_id: noteId }
  if (options?.force) body.force = true
  return client.post('/evaluation/note', body, {
    ...options,
    timeout: EVALUATE_NOTE_TIMEOUT_MS,
  }) as unknown as Promise<{
    account_id: string
    note_id: string
    evaluation_result: EvaluationResultResponse['evaluation_result']
    thresholds?: EvaluationResultResponse['thresholds']
    evaluation_id?: string | null
    status?: EvaluationResultResponse['status']
    degraded?: boolean
    coverage?: EvaluationResultResponse['coverage']
    data_as_of?: string | null
    source?: EvaluationSourceMetadata
    evaluated_at?: string | null
    evaluator_fingerprint?: string | null
    stale?: boolean
    stale_at?: string | null
    cache_hit?: boolean
    snapshot_id?: string | null
    contract_version?: string | null
  }>
}

/** Restore the latest persisted historical-note RQGM run after refresh. */
export async function getLatestNoteEvaluation(
  accountId: string,
  noteId: string,
  options?: RequestOptions,
): Promise<{
  account_id: string
  note_id: string
  evaluation_result?: EvaluationResultResponse['evaluation_result'] | null
  thresholds?: EvaluationResultResponse['thresholds']
  evaluation_id?: string | null
  status?: EvaluationResultResponse['status']
  degraded?: boolean
  coverage?: EvaluationResultResponse['coverage']
  data_as_of?: string | null
  source?: EvaluationSourceMetadata
  evaluated_at?: string | null
  evaluator_fingerprint?: string | null
  stale?: boolean
  stale_at?: string | null
  snapshot_id?: string | null
  contract_version?: string | null
}> {
  return client.get(`/evaluation/note/${accountId}/${noteId}/latest`, options) as unknown as Promise<{
    account_id: string
    note_id: string
    evaluation_result?: EvaluationResultResponse['evaluation_result'] | null
    thresholds?: EvaluationResultResponse['thresholds']
    evaluation_id?: string | null
    status?: EvaluationResultResponse['status']
    degraded?: boolean
    coverage?: EvaluationResultResponse['coverage']
    data_as_of?: string | null
    source?: EvaluationSourceMetadata
    evaluated_at?: string | null
    evaluator_fingerprint?: string | null
    stale?: boolean
    stale_at?: string | null
    snapshot_id?: string | null
    contract_version?: string | null
  }>
}

// 获取评估历史趋势（overall_score 时序 + 各维度均值）
export async function getEvaluationTrend(
  accountId?: string,
  limit = 100,
  options?: RequestOptions,
): Promise<EvaluationTrendResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (accountId) params.set('account_id', accountId)
  return client.get(`/evaluation/trend?${params.toString()}`, options) as unknown as EvaluationTrendResponse
}
