// frontend/tests/composables/useLoading.spec.ts
import { describe, it, expect } from 'vitest'
import { useLoading } from '@/composables/useLoading'
import type { WorkflowPhase } from '@/types'

describe('useLoading', () => {
  it('maps phase to progress percent correctly', () => {
    const { phaseToPercent } = useLoading()

    expect(phaseToPercent('idle')).toBe(0)
    expect(phaseToPercent('scouting')).toBe(10)
    expect(phaseToPercent('planning')).toBe(20)
    expect(phaseToPercent('creating')).toBe(40)
    expect(phaseToPercent('reviewing')).toBe(60)
    expect(phaseToPercent('publishing')).toBe(80)
    expect(phaseToPercent('analyzing')).toBe(90)
    expect(phaseToPercent('engaging')).toBe(95)
    expect(phaseToPercent('completed')).toBe(100)
  })

  it('returns correct overlay phases', () => {
    const { isOverlayPhase } = useLoading()

    expect(isOverlayPhase('scouting')).toBe(true)
    expect(isOverlayPhase('planning')).toBe(true)
    expect(isOverlayPhase('publishing')).toBe(true)
    expect(isOverlayPhase('creating')).toBe(false)
  })

  it('provides phase color mapping', () => {
    const { phaseToColor } = useLoading()

    expect(phaseToColor('scouting')).toBe('#f43f5e')
    expect(phaseToColor('planning')).toBe('#8b5cf6')
    expect(phaseToColor('creating')).toBe('#14b8a6')
    expect(phaseToColor('reviewing')).toBe('#f59e0b')
  })

  it('returns 0 for error phase', () => {
    const { phaseToPercent } = useLoading()
    expect(phaseToPercent('error')).toBe(0)
  })

  it('returns error color for error phase', () => {
    const { phaseToColor } = useLoading()
    expect(phaseToColor('error')).toBe('#f43f5e')
  })

  it('exposes PHASE_PERCENT_MAP for external use', () => {
    const { PHASE_PERCENT_MAP } = useLoading()

    expect(PHASE_PERCENT_MAP).toBeDefined()
    expect(PHASE_PERCENT_MAP.idle).toBe(0)
    expect(PHASE_PERCENT_MAP.completed).toBe(100)
  })

  it('exposes PHASE_COLOR_MAP for external use', () => {
    const { PHASE_COLOR_MAP } = useLoading()

    expect(PHASE_COLOR_MAP).toBeDefined()
    expect(PHASE_COLOR_MAP.idle).toBe('#94a3b8')
    expect(PHASE_COLOR_MAP.completed).toBe('#10b981')
  })

  it('handles all WorkflowPhase values in percent map', () => {
    const { PHASE_PERCENT_MAP } = useLoading()
    const phases: WorkflowPhase[] = [
      'idle', 'scouting', 'planning', 'creating',
      'reviewing', 'publishing', 'analyzing', 'engaging',
      'completed', 'error'
    ]

    phases.forEach(phase => {
      expect(PHASE_PERCENT_MAP[phase]).toBeDefined()
      expect(typeof PHASE_PERCENT_MAP[phase]).toBe('number')
    })
  })

  it('handles all WorkflowPhase values in color map', () => {
    const { PHASE_COLOR_MAP } = useLoading()
    const phases: WorkflowPhase[] = [
      'idle', 'scouting', 'planning', 'creating',
      'reviewing', 'publishing', 'analyzing', 'engaging',
      'completed', 'error'
    ]

    phases.forEach(phase => {
      expect(PHASE_COLOR_MAP[phase]).toBeDefined()
      expect(typeof PHASE_COLOR_MAP[phase]).toBe('string')
      expect(PHASE_COLOR_MAP[phase]).toMatch(/^#[0-9a-f]{6}$/i)
    })
  })
})