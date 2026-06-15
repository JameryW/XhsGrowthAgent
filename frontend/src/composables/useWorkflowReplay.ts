import { computed } from 'vue'
import { useWorkflowStore } from '@/stores'
import type { CheckpointSnapshot } from '@/types/workflow'

type NodeStatus = 'completed' | 'running' | 'pending' | 'error'

export function useWorkflowReplay() {
  const store = useWorkflowStore()

  const threadId = computed(() => store.activeThreadId)
  const activeCheckpointId = computed(() => store.activeCheckpointId)
  const replayCheckpoints = computed(() => store.replayCheckpoints)
  const effectiveState = computed(() => store.effectiveState)
  const workflowLabel = computed(() => store.workflowState?.label || '')
  const workflowMode = computed<'trend' | 'brief'>(() => effectiveState.value?.workflow_mode || 'trend')

  const pipelineSteps = computed<string[]>(() => {
    const isBrief = workflowMode.value === 'brief'
    return isBrief
      ? ['briefing', 'creating', 'reviewing', 'publishing', 'analyzing']
      : ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing']
  })

  const phaseAlias: Record<string, string> = {
    engaging: 'publishing',
  }

  function phaseToIndex(phase: string): number {
    const mapped = phaseAlias[phase] || phase
    const idx = pipelineSteps.value.indexOf(mapped)
    if (idx >= 0) return idx
    if (phase === 'completed') return pipelineSteps.value.length
    return -1
  }

  const selectedCheckpoint = computed<CheckpointSnapshot | null>(() => {
    if (!activeCheckpointId.value) return null
    return replayCheckpoints.value.find(c => c.checkpoint_id === activeCheckpointId.value) || null
  })

  const selectedAgent = computed(() => selectedCheckpoint.value?.current_agent || '')

  const phaseAgentMap = computed<Record<string, string>>(() => {
    const isBrief = workflowMode.value === 'brief'
    return {
      ...(isBrief ? { briefing: 'brief_analyzer' } : { scouting: 'trend_scout', planning: 'content_strategist' }),
      creating: isBrief ? 'viral_matcher' : 'copywriter',
      reviewing: 'review_gate',
      publishing: 'publisher',
      analyzing: 'analyst',
    }
  })

  function getNodeStatus(phase: string): NodeStatus {
    const cp = selectedCheckpoint.value
    if (cp) {
      const cpPhase = cp.phase
      if (cpPhase === 'completed') return 'completed'
      const idx = phaseToIndex(phase)
      const cpIdx = phaseToIndex(cpPhase)
      if (cpIdx < 0) {
        const cpAgent = cp.current_agent
        const agentPhase = Object.entries(phaseAgentMap.value).find(([_, agent]) => agent === cpAgent)
        if (agentPhase) {
          const resolvedIdx = phaseToIndex(agentPhase[0])
          if (idx < 0 || resolvedIdx < 0) return 'pending'
          if (idx < resolvedIdx) return 'completed'
          if (idx === resolvedIdx) return 'running'
          return 'pending'
        }
        return 'pending'
      }
      if (cpPhase === 'error') {
        if (idx < cpIdx) return 'completed'
        if (idx === cpIdx) return 'error'
        return 'pending'
      }
      if (idx < cpIdx) return 'completed'
      if (idx === cpIdx) return 'running'
      return 'pending'
    }
    if (!effectiveState.value) return 'pending'
    const currentPhase = effectiveState.value.phase
    const currentStatus = effectiveState.value.status
    if (currentPhase === 'completed' || currentStatus === 'completed') return 'completed'
    const idx = phaseToIndex(phase)
    const currentIdx = phaseToIndex(currentPhase)
    if (currentIdx < 0) {
      const cpAgent = (effectiveState.value as any).current_agent
      const agentPhase = Object.entries(phaseAgentMap.value).find(([_, agent]) => agent === cpAgent)
      if (agentPhase) {
        const resolvedIdx = phaseToIndex(agentPhase[0])
        if (idx < 0 || resolvedIdx < 0) return 'pending'
        if (idx < resolvedIdx) return 'completed'
        if (idx === resolvedIdx) return 'running'
        return 'pending'
      }
      return 'pending'
    }
    if (idx < 0) return 'pending'
    if (idx < currentIdx) return 'completed'
    if (idx === currentIdx) return 'running'
    return 'pending'
  }

  function findCheckpointForAgent(agent: string): string | null {
    const cp = replayCheckpoints.value.find(c => c.current_agent === agent)
    return cp ? cp.checkpoint_id : null
  }

  function handleNodeClick(phase: string) {
    const agent = phaseAgentMap.value[phase] || phase
    let cpId = findCheckpointForAgent(agent)
    if (!cpId) {
      // Order matches backend graph: brief = viral_matcher → blogger_scout → blogger_gate → copywriter → draft_gate → shooting_planner → content_analyzer → version_generator → choice_gate → visual_designer
      const phaseAgents: Record<string, string[]> = {
        creating: ['viral_matcher', 'blogger_scout', 'blogger_gate', 'copywriter', 'draft_gate', 'shooting_planner', 'content_analyzer', 'version_generator', 'choice_gate', 'visual_designer'],
        reviewing: ['review_gate', 'revise_content', 'visual_designer', 'copywriter'],
        publishing: ['publisher', 'engagement'],
        briefing: ['brief_analyzer', 'brief_gate'],
      }
      for (const fallback of phaseAgents[phase] || []) {
        cpId = findCheckpointForAgent(fallback)
        if (cpId) break
      }
    }
    if (cpId) store.selectCheckpoint(cpId)
  }

  function isNodeSelected(phase: string): boolean {
    if (!activeCheckpointId.value || !selectedCheckpoint.value) return false
    const cpPhase = selectedCheckpoint.value.phase
    if (cpPhase === phase) return true
    const cpAgent = selectedCheckpoint.value.current_agent
    // Primary mapping: agent → phase (1:1, takes priority)
    const agentPhase = Object.entries(phaseAgentMap.value).find(([_, agent]) => agent === cpAgent)
    if (agentPhase) return agentPhase[0] === phase
    // Fallback: match the FIRST phase whose agent list includes this agent
    // (prevents briefing & creating both being selected for shared agents)
    // Brief mode: briefing = brief_analyzer + brief_gate; creating = all post-gate agents
    const phaseAgents: Record<string, string[]> = {
      creating: ['viral_matcher', 'blogger_scout', 'blogger_gate', 'copywriter', 'draft_gate', 'shooting_planner', 'content_analyzer', 'version_generator', 'choice_gate', 'visual_designer'],
      briefing: ['brief_analyzer', 'brief_gate'],
    }
    for (const [p, agents] of Object.entries(phaseAgents)) {
      if (agents.includes(cpAgent)) return p === phase
    }
    return false
  }

  function hasDataForAgent(agent: string, cp: CheckpointSnapshot): boolean {
    const has = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
    if (agent === 'trend_scout') return has(cp.trend_data)
    if (agent === 'content_strategist') return has(cp.content_plan)
    if (['copywriter', 'brief_analyzer', 'brief_gate', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'shooting_planner', 'content_analyzer', 'choice_gate', 'version_generator'].includes(agent)) return has(cp.copy_content) || hasMeaningfulData(cp.visual_plan) || has((cp as any).brief_content) || has((cp as any).shooting_plan)
    if (agent === 'visual_designer') return has(cp.copy_content) || hasMeaningfulData(cp.visual_plan)
    if (['review_gate', 'revise_content'].includes(agent)) return has(cp.copy_content) || hasMeaningfulData(cp.visual_plan) || has((cp as any).brief_content)
    if (['publisher', 'engagement'].includes(agent)) return has(cp.publish_result)
    if (agent === 'analyst') return has(cp.analytics)
    return false
  }

  function hasMeaningfulData(v: unknown): boolean {
    if (!v || typeof v !== 'object') return false
    const obj = v as Record<string, unknown>
    return Object.values(obj).some(val => {
      if (val === undefined || val === null || val === '') return false
      if (Array.isArray(val)) return val.length > 0
      if (typeof val === 'object') return Object.keys(val as Record<string, unknown>).length > 0
      return true
    })
  }

  const resolvedShootingPlan = computed(() => {
    const sp = (selectedCheckpoint.value as any)?.shooting_plan
    if (!sp || typeof sp !== 'object') return sp
    const keys = Object.keys(sp)
    if (keys.length === 1 && keys[0] === 'raw_content' && typeof sp.raw_content === 'string') {
      try {
        let raw = sp.raw_content.trim()
        if (raw.startsWith('```')) {
          raw = raw.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?```\s*$/, '')
        }
        return JSON.parse(raw)
      } catch {
        try {
          let raw = sp.raw_content.trim()
          if (raw.startsWith('```')) {
            raw = raw.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?```\s*$/, '')
          }
          return JSON.parse(repairBrackets(raw))
        } catch {
          return sp
        }
      }
    }
    return sp
  })

  function repairBrackets(jsonStr: string): string {
    const result: string[] = []
    const stack: string[] = []
    for (const ch of jsonStr) {
      if (ch === '{' || ch === '[') {
        stack.push(ch)
        result.push(ch)
      } else if (ch === '}' && stack.length > 0 && stack[stack.length - 1] === '[') {
        stack.pop()
        result.push(']')
      } else if (ch === ']' && stack.length > 0 && stack[stack.length - 1] === '{') {
        stack.pop()
        result.push('}')
      } else if (ch === '}' || ch === ']') {
        if (stack.length > 0) stack.pop()
        result.push(ch)
      } else {
        result.push(ch)
      }
    }
    return result.join('')
  }

  function formatDate(iso: string | null) {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  function formatNum(n?: number): string {
    if (n === undefined || n === null) return '—'
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return n.toLocaleString()
  }

  return {
    threadId,
    activeCheckpointId,
    replayCheckpoints,
    effectiveState,
    workflowLabel,
    workflowMode,
    pipelineSteps,
    selectedCheckpoint,
    selectedAgent,
    resolvedShootingPlan,
    phaseAgentMap,
    getNodeStatus,
    handleNodeClick,
    isNodeSelected,
    hasDataForAgent,
    hasMeaningfulData,
    formatDate,
    formatNum,
    findCheckpointForAgent,
  }
}
