// frontend/src/composables/useLoading.ts
import type { WorkflowPhase } from '@/types'

/**
 * Phase to progress percent mapping
 * Represents the progress percentage at each workflow phase
 */
const PHASE_PERCENT_MAP: Record<WorkflowPhase, number> = {
  idle: 0,
  scouting: 10,
  planning: 20,
  creating: 40,
  briefing: 15,
  reviewing: 60,
  publishing: 80,
  analyzing: 90,
  engaging: 95,
  completed: 100,
  error: 0,
  paused: 0,
  cancelled: 0
}

/**
 * Phase to color mapping
 * Tailwind CSS color hex values for each phase
 */
const PHASE_COLOR_MAP: Record<WorkflowPhase, string> = {
  idle: '#94a3b8',      // slate-400
  scouting: '#f43f5e',  // rose-500
  planning: '#8b5cf6',  // violet-500
  creating: '#14b8a6',  // teal-500
  briefing: '#8b5cf6',  // violet-500
  reviewing: '#f59e0b', // amber-500
  publishing: '#3b82f6', // blue-500
  analyzing: '#22c55e', // green-500
  engaging: '#22c55e',  // green-500
  completed: '#10b981', // emerald-500
  error: '#f43f5e',     // rose-500
  paused: '#f59e0b',    // amber-500
  cancelled: '#94a3b8'  // slate-400
}

/** Phases whose work is long-running enough to show a blocking overlay. */
const OVERLAY_PHASES: readonly WorkflowPhase[] = ['scouting', 'planning', 'publishing']

/**
 * Composable for loading state management
 * Provides phase-to-progress and phase-to-color mappings
 */
export function useLoading() {
  /**
   * Convert workflow phase to progress percentage
   * @param phase - Current workflow phase
   * @returns Progress percentage (0-100)
   */
  const phaseToPercent = (phase: WorkflowPhase): number => {
    return PHASE_PERCENT_MAP[phase] || 0
  }

  /**
   * Convert workflow phase to color
   * @param phase - Current workflow phase
   * @returns Hex color string
   */
  const phaseToColor = (phase: WorkflowPhase): string => {
    return PHASE_COLOR_MAP[phase] || '#94a3b8'
  }

  const isOverlayPhase = (phase: WorkflowPhase): boolean => {
    return OVERLAY_PHASES.includes(phase)
  }

  return {
    phaseToPercent,
    phaseToColor,
    isOverlayPhase,
    PHASE_PERCENT_MAP,
    PHASE_COLOR_MAP
  }
}
