// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { getDashboardHero } from '@/composables/dashboardHero'
import type { WorkflowPhase, WorkflowStatus } from '@/types/workflow'

const t = (key: string) => key

function hero(phase: WorkflowPhase, status: WorkflowStatus, progress = 42) {
  return getDashboardHero({ phase, status, progress }, t)
}

describe('getDashboardHero', () => {
  it.each([
    ['idle', 'idle', 'dashboard.hero.idleTitle', 'pink'],
    ['scouting', 'running', 'dashboard.hero.runningTitle', 'cyan'],
    ['creating', 'awaiting_draft', 'dashboard.hero.waitingTitle', 'amber'],
    ['reviewing', 'awaiting_review', 'dashboard.hero.reviewTitle', 'violet'],
    ['completed', 'completed', 'dashboard.hero.completedTitle', 'emerald'],
    ['error', 'error', 'dashboard.hero.errorTitle', 'rose'],
  ] as const)('maps %s/%s to %s state', (phase, status, title, tone) => {
    const result = hero(phase, status)
    expect(result.title).toBe(title)
    expect(result.tone).toBe(tone)
    expect(result.progress).toBe(42)
  })

  it('clamps invalid progress to the visible 0–100 range', () => {
    expect(hero('creating', 'running', -5).progress).toBe(0)
    expect(hero('creating', 'running', 120).progress).toBe(100)
    expect(getDashboardHero({ phase: 'creating', status: 'running', progress: Number.NaN }, t).progress).toBe(0)
  })

  it('labels replay snapshots as historical instead of completed', () => {
    const result = getDashboardHero({ phase: 'completed', status: 'completed', progress: 100, isReplay: true }, t)
    expect(result.icon).toBe('History')
    expect(result.title).toBe('dashboard.hero.replayTitle')
    expect(result.status).toBe('dashboard.hero.replayStatus')
    expect(result.tone).toBe('violet')
  })
})
