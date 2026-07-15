import type { WorkflowPhase, WorkflowStatus } from '@/types/workflow'

export type DashboardHeroTone = 'emerald' | 'rose' | 'violet' | 'amber' | 'cyan' | 'pink'

export interface DashboardHeroInput {
  phase: WorkflowPhase
  status: WorkflowStatus
  progress?: number | null
  /** Replay snapshots are historical views, even though their synthetic state
   * uses `completed` as a status for read-only rendering. */
  isReplay?: boolean
}

export interface DashboardHeroCopy {
  icon: string
  title: string
  description: string
  status: string
  tone: DashboardHeroTone
  progress: number
}

type Translate = (key: string, params?: Record<string, unknown>) => string

function clampProgress(progress: number | null | undefined): number {
  const value = typeof progress === 'number' && Number.isFinite(progress) ? progress : 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

/**
 * Resolve the Dashboard's first-screen state without coupling it to Pinia.
 * Keeping this mapping pure makes each user-visible state easy to verify and
 * keeps replay/live state semantics in the caller (`effectiveState`).
 */
export function getDashboardHero(input: DashboardHeroInput, t: Translate): DashboardHeroCopy {
  const progress = clampProgress(input.progress)

  if (input.isReplay) {
    return {
      icon: 'History',
      title: t('dashboard.hero.replayTitle'),
      description: t('dashboard.hero.replayDescription'),
      status: t('dashboard.hero.replayStatus'),
      tone: 'violet',
      progress,
    }
  }

  if (input.phase === 'completed' || input.status === 'completed') {
    return {
      icon: 'CheckCircle',
      title: t('dashboard.hero.completedTitle'),
      description: t('dashboard.hero.completedDescription'),
      status: t('dashboard.phase.completed'),
      tone: 'emerald',
      progress,
    }
  }
  if (input.phase === 'error' || input.status === 'error') {
    return {
      icon: 'AlertCircle',
      title: t('dashboard.hero.errorTitle'),
      description: t('dashboard.hero.errorDescription'),
      status: t('dashboard.phase.error'),
      tone: 'rose',
      progress,
    }
  }
  if (input.status === 'awaiting_review') {
    return {
      icon: 'ClipboardCheck',
      title: t('dashboard.hero.reviewTitle'),
      description: t('dashboard.hero.reviewDescription'),
      status: t('dashboard.phase.awaitingReview'),
      tone: 'violet',
      progress,
    }
  }
  if (
    input.status === 'awaiting_brief' ||
    input.status === 'awaiting_draft' ||
    input.status === 'awaiting_choice' ||
    input.status === 'awaiting_ripple_decision' ||
    input.status === 'awaiting_blogger_selection' ||
    input.status === 'paused' ||
    input.status === 'stale'
  ) {
    return {
      icon: 'Clock',
      title: t('dashboard.hero.waitingTitle'),
      description: t('dashboard.hero.waitingDescription'),
      status: t('dashboard.header.awaitingAction'),
      tone: 'amber',
      progress,
    }
  }
  if (input.status === 'running') {
    return {
      icon: 'Sparkles',
      title: t('dashboard.hero.runningTitle'),
      description: t('dashboard.hero.runningDescription'),
      status: t('dashboard.header.running'),
      tone: 'cyan',
      progress,
    }
  }
  return {
    icon: 'Rocket',
    title: t('dashboard.hero.idleTitle'),
    description: t('dashboard.hero.idleDescription'),
    status: t('dashboard.header.idle'),
    tone: 'pink',
    progress,
  }
}
