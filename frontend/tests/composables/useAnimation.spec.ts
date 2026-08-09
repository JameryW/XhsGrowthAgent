// @vitest-environment node
// frontend/tests/composables/useAnimation.spec.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { animatedCounter } from '@/composables/useAnimation'
import { prefersReducedMotion } from '@/composables/useReducedMotion'

describe('useAnimation', () => {
  let mockPerformanceNow: ReturnType<typeof vi.fn>
  let rafIdCounter: number
  let pendingCallbacks: Array<{ id: number; callback: FrameRequestCallback }>

  beforeEach(() => {
    prefersReducedMotion.value = false
    mockPerformanceNow = vi.fn(() => 0)
    rafIdCounter = 0
    pendingCallbacks = []

    // Mock performance.now()
    vi.stubGlobal('performance', {
      now: mockPerformanceNow
    })

    // Mock requestAnimationFrame - just stores callbacks
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++rafIdCounter
      pendingCallbacks.push({ id, callback })
      return id
    })

    // Mock cancelAnimationFrame
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      pendingCallbacks = pendingCallbacks.filter(c => c.id !== id)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // Helper to run all pending callbacks with a given time
  function runCallbacksAtTime(time: number) {
    mockPerformanceNow.mockReturnValue(time)
    const callbacksToRun = [...pendingCallbacks]
    pendingCallbacks = []
    callbacksToRun.forEach(({ callback }) => callback(time))
  }

  it('animates counter from start to end value correctly', async () => {
    const values: number[] = []

    const promise = animatedCounter(0, 100, 500, (value) => {
      values.push(value)
    })

    // Initial call at time 0
    runCallbacksAtTime(0)
    expect(values[values.length - 1]).toBe(0)

    // Halfway through
    runCallbacksAtTime(250)
    expect(values[values.length - 1]).toBeGreaterThan(50)

    // Complete
    runCallbacksAtTime(500)

    await promise

    expect(values[values.length - 1]).toBe(100)
  })

  it('respects duration parameter', async () => {
    const values: number[] = []

    const promise = animatedCounter(0, 10, 300, (value) => {
      values.push(value)
    })

    // Start
    runCallbacksAtTime(0)

    // Halfway - not complete
    runCallbacksAtTime(150)
    expect(values[values.length - 1]).toBeLessThan(10)

    // Complete
    runCallbacksAtTime(300)

    await promise

    expect(values[values.length - 1]).toBe(10)
  })

  it('applies ease-out easing for smoother animation', async () => {
    const values: number[] = []

    const promise = animatedCounter(0, 100, 100, (value) => {
      values.push(value)
    })

    // Start
    runCallbacksAtTime(0)

    // At 50% progress, ease-out cubic gives 87.5% value
    runCallbacksAtTime(50)
    const halfwayValue = values[values.length - 1]
    expect(halfwayValue).toBeGreaterThan(50) // Should be ~88

    // Complete
    runCallbacksAtTime(100)

    await promise

    expect(values[values.length - 1]).toBe(100)
  })

  it('rounds values to integers', async () => {
    const values: number[] = []

    const promise = animatedCounter(0, 10, 50, (value) => {
      values.push(value)
    })

    runCallbacksAtTime(0)
    runCallbacksAtTime(50)

    await promise

    // All values should be integers
    values.forEach(value => {
      expect(Number.isInteger(value)).toBe(true)
    })
  })

  it('handles zero duration animation', async () => {
    const values: number[] = []

    const promise = animatedCounter(0, 100, 0, (value) => {
      values.push(value)
    })

    await promise

    expect(values.length).toBe(1)
    expect(values[0]).toBe(100)
  })

  it('jumps to the final value when reduced motion is enabled', async () => {
    prefersReducedMotion.value = true
    const values: number[] = []

    await animatedCounter(0, 100, 500, (value) => {
      values.push(value)
    })

    expect(values).toEqual([100])
    expect(pendingCallbacks).toHaveLength(0)
  })

  it('handles negative to positive range', async () => {
    const values: number[] = []

    const promise = animatedCounter(-50, 50, 200, (value) => {
      values.push(value)
    })

    runCallbacksAtTime(0)
    runCallbacksAtTime(200)

    await promise

    expect(values[0]).toBe(-50)
    expect(values[values.length - 1]).toBe(50)
  })

  it('handles descending range (positive to negative)', async () => {
    const values: number[] = []

    const promise = animatedCounter(50, -50, 200, (value) => {
      values.push(value)
    })

    runCallbacksAtTime(0)
    runCallbacksAtTime(200)

    await promise

    expect(values[0]).toBe(50)
    expect(values[values.length - 1]).toBe(-50)
  })

  it('starts from correct start value', async () => {
    const values: number[] = []

    const promise = animatedCounter(25, 75, 100, (value) => {
      values.push(value)
    })

    runCallbacksAtTime(0)

    expect(values[0]).toBe(25)

    runCallbacksAtTime(100)
    await promise
  })
})
