import client from './client'
import { prefetchRouteChunk } from '@/utils/routePrefetch'

export type AgentPrewarmMode = 'free' | 'workflow'

export interface AgentPrewarmResult {
  status: 'warming' | 'ready'
  mode: AgentPrewarmMode
  session_id?: string
}

/** Fire-and-forget omp session warm-up (does not wait for subprocess ready). */
export async function prewarmAgentSession(
  mode: AgentPrewarmMode = 'free',
): Promise<AgentPrewarmResult> {
  return client.post(`/agent/prewarm?mode=${encodeURIComponent(mode)}`) as unknown as AgentPrewarmResult
}

/** Prefetch the heavy AgentTUI route chunk (free creation entry). */
export function prefetchAgentTuiChunk(): void {
  void prefetchRouteChunk('tui')
}
