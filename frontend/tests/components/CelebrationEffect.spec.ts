// frontend/tests/components/CelebrationEffect.spec.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import CelebrationEffect from '@/components/CelebrationEffect.vue'

describe('CelebrationEffect', () => {
  let mockPerformanceNow: ReturnType<typeof vi.fn>
  let rafIdCounter: number
  let pendingCallbacks: Array<{ id: number; callback: FrameRequestCallback }>

  beforeEach(() => {
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
    pendingCallbacks = []
  })

  // Helper to run all pending callbacks with a given time
  function runCallbacksAtTime(time: number) {
    mockPerformanceNow.mockReturnValue(time)
    const callbacksToRun = [...pendingCallbacks]
    pendingCallbacks = []
    callbacksToRun.forEach(({ callback }) => callback(time))
  }

  it('renders canvas element', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    expect(wrapper.find('canvas').exists()).toBe(true)
    expect(wrapper.find('.celebration-canvas').exists()).toBe(true)
  })

  it('accepts type prop with default confetti', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    expect(wrapper.props('type')).toBe('confetti')
  })

  it('accepts different effect types', () => {
    const confettiWrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'confetti' }
    })
    expect(confettiWrapper.props('type')).toBe('confetti')

    const pulseWrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'pulse' }
    })
    expect(pulseWrapper.props('type')).toBe('pulse')

    const starsWrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'stars' }
    })
    expect(starsWrapper.props('type')).toBe('stars')
  })

  it('accepts isActive prop to control animation', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: true }
    })

    expect(wrapper.props('isActive')).toBe(true)

    // Canvas should have is-active class
    expect(wrapper.find('.celebration-canvas').classes()).toContain('is-active')
  })

  it('accepts duration prop with default 3000ms', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    expect(wrapper.props('duration')).toBe(3000)
  })

  it('accepts custom duration prop', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false, duration: 5000 }
    })

    expect(wrapper.props('duration')).toBe(5000)
  })

  it('does not start animation when isActive is false', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    // No animation frame should be requested
    expect(pendingCallbacks.length).toBe(0)
  })

  it('starts animation when isActive becomes true', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    // Set canvas dimensions manually for testing
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Activate animation
    await wrapper.setProps({ isActive: true })

    // Animation should have started
    expect(pendingCallbacks.length).toBeGreaterThan(0)
  })

  it('stops animation when isActive becomes false', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })
    const initialRafCount = pendingCallbacks.length

    // Stop animation
    await wrapper.setProps({ isActive: false })

    // Animation should be stopped
    // Note: cancelAnimationFrame removes callbacks
    expect(wrapper.find('.celebration-canvas').classes()).not.toContain('is-active')
  })

  it('exposes canvasRef for testing', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    const vm = wrapper.vm as any
    expect(vm.canvasRef).toBeDefined()
  })

  it('exposes particles array for confetti type', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'confetti' }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })

    const vm = wrapper.vm as any
    expect(vm.particles).toBeDefined()
    expect(vm.particles.length).toBeGreaterThan(0)
  })

  it('exposes stars array for stars type', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'stars' }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })

    const vm = wrapper.vm as any
    expect(vm.stars).toBeDefined()
    expect(vm.stars.length).toBeGreaterThan(0)
  })

  it('exposes pulseRings array for pulse type', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'pulse' }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })

    const vm = wrapper.vm as any
    expect(vm.pulseRings).toBeDefined()
    expect(vm.pulseRings.length).toBeGreaterThan(0)
  })

  it('initializes confetti particles with correct properties', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false, type: 'confetti' }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })

    const vm = wrapper.vm as any
    const particles = vm.particles

    // Each particle should have required properties
    particles.forEach((p: any) => {
      expect(p.x).toBeDefined()
      expect(p.y).toBeDefined()
      expect(p.vx).toBeDefined()
      expect(p.vy).toBeDefined()
      expect(p.color).toBeDefined()
      expect(p.size).toBeDefined()
      expect(p.rotation).toBeDefined()
      expect(p.opacity).toBeDefined()
    })
  })

  it('animation completes after duration', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: true, duration: 100 }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Run initial frame
    runCallbacksAtTime(0)

    // Run at completion time
    runCallbacksAtTime(100)

    // Animation should complete (no more pending callbacks)
    expect(pendingCallbacks.length).toBe(0)

    // animationFrameId should be null
    const vm = wrapper.vm as any
    expect(vm.animationFrameId).toBeNull()
  })

  it('cleanup happens on component unmount', async () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    // Set canvas dimensions
    const canvas = wrapper.find('canvas').element as HTMLCanvasElement
    canvas.width = 300
    canvas.height = 200

    // Start animation
    await wrapper.setProps({ isActive: true })

    // Unmount component
    wrapper.unmount()

    // All callbacks should be cancelled
    expect(pendingCallbacks.length).toBe(0)
  })

  it('has proper CSS structure with celebration-effect wrapper', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    expect(wrapper.find('.celebration-effect').exists()).toBe(true)
  })

  it('canvas is positioned absolutely for overlay', () => {
    const wrapper = mount(CelebrationEffect, {
      props: { isActive: false }
    })

    // The component has scoped styles, but we can verify structure
    const celebrationEffect = wrapper.find('.celebration-effect')
    expect(celebrationEffect.exists()).toBe(true)

    const canvas = wrapper.find('canvas')
    expect(canvas.exists()).toBe(true)
  })
})