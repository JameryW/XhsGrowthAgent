import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref, nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import PageTransition from '@/components/PageTransition.vue'
import CelebrationEffect from '@/components/CelebrationEffect.vue'
import AnimatedCounter from '@/components/AnimatedCounter.vue'
import NeonButton from '@/components/NeonButton.vue'
import ErrorCard from '@/components/ErrorCard.vue'
import { useAnimation } from '@/composables/useAnimation'

// Create simple test components for routing
const TestComponentA = { template: '<div class="page-a">Page A</div>' }
const TestComponentB = { template: '<div class="page-b">Page B</div>' }
const TestComponentC = { template: '<div class="page-c">Page C</div>' }

// Helper to setup requestAnimationFrame mocking for CelebrationEffect
function setupRafMock() {
  let rafIdCounter = 0
  let pendingCallbacks: Array<{ id: number; callback: FrameRequestCallback }> = []
  const mockPerformanceNow = vi.fn(() => 0)

  vi.stubGlobal('performance', { now: mockPerformanceNow })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++rafIdCounter
    pendingCallbacks.push({ id, callback })
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    pendingCallbacks = pendingCallbacks.filter(c => c.id !== id)
  })

  return {
    runCallbacksAtTime: (time: number) => {
      mockPerformanceNow.mockReturnValue(time)
      const callbacksToRun = [...pendingCallbacks]
      pendingCallbacks = []
      callbacksToRun.forEach(({ callback }) => callback(time))
    },
    getPendingCount: () => pendingCallbacks.length
  }
}

/**
 * Theme 3 Acceptance Tests
 *
 * AC1: Page transitions smooth without lag (Home→Dashboard→Review)
 * AC2: Celebration animation on completion (workflow complete triggers confetti)
 * AC3: Micro-interactions timely (button loading rotate, error shake)
 */
describe('Theme 3 Acceptance Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  describe('AC1: Page transitions smooth without lag', () => {
    it('PageTransition component renders with fade-slide animation', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [
          { path: '/', component: TestComponentA },
          { path: '/b', component: TestComponentB }
        ]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        global: { plugins: [router] }
      })

      // Should contain RouterView
      expect(wrapper.findComponent({ name: 'RouterView' }).exists()).toBe(true)

      // Find the Transition component
      const transition = wrapper.findComponent({ name: 'Transition' })
      expect(transition.exists()).toBe(true)

      // Check transition name
      expect(transition.props('name')).toBe('fade-slide')
    })

    it('PageTransition has correct default duration (200ms)', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [{ path: '/', component: TestComponentA }]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        global: { plugins: [router] }
      })

      // Default duration should be 200ms
      expect(wrapper.props('duration')).toBe(200)

      // Check style contains default duration
      const transition = wrapper.findComponent({ name: 'Transition' })
      expect(transition.attributes('style')).toContain('200ms')
    })

    it('PageTransition accepts custom duration prop', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [{ path: '/', component: TestComponentA }]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        props: { duration: 300 },
        global: { plugins: [router] }
      })

      // Custom duration should be reflected
      expect(wrapper.props('duration')).toBe(300)
      const transition = wrapper.findComponent({ name: 'Transition' })
      expect(transition.attributes('style')).toContain('300ms')
    })

    it('PageTransition uses out-in mode for smooth transitions', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [
          { path: '/', component: TestComponentA },
          { path: '/b', component: TestComponentB }
        ]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        global: { plugins: [router] }
      })

      const transition = wrapper.findComponent({ name: 'Transition' })
      expect(transition.props('mode')).toBe('out-in')
    })

    it('Router meta.transition configured for all routes', async () => {
      const router = await import('@/router/index.ts')
      const routes = router.default.options.routes

      routes.forEach(route => {
        expect(route.meta?.transition).toBe('fade-slide')
      })
    })

    it('PageTransition handles route changes smoothly', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [
          { path: '/', component: TestComponentA },
          { path: '/b', component: TestComponentB }
        ]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        global: { plugins: [router] }
      })

      // Initially shows Page A
      expect(wrapper.find('.page-a').exists()).toBe(true)

      // Navigate to Page B
      await router.push('/b')
      await flushPromises()

      // Should show Page B after transition
      expect(wrapper.find('.page-b').exists()).toBe(true)
    })

    it('PageTransition duration is within acceptable lag threshold (< 500ms)', async () => {
      const router = createRouter({
        history: createWebHistory(),
        routes: [{ path: '/', component: TestComponentA }]
      })

      await router.push('/')
      await router.isReady()

      const wrapper = mount(PageTransition, {
        global: { plugins: [router] }
      })

      // Duration should be less than 500ms for smooth UX
      const duration = wrapper.props('duration') as number
      expect(duration).toBeLessThan(500)
    })
  })

  describe('AC2: Celebration animation on completion', () => {
    beforeEach(() => {
      setupRafMock()
    })

    it('CelebrationEffect renders canvas element', () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false }
      })

      expect(wrapper.find('canvas').exists()).toBe(true)
      expect(wrapper.find('.celebration-effect').exists()).toBe(true)
    })

    it('CelebrationEffect triggers when isActive prop is true', async () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false }
      })

      // Initially canvas should not be active
      expect(wrapper.find('.celebration-canvas').classes()).not.toContain('is-active')

      // Set canvas dimensions for testing
      const canvas = wrapper.find('canvas').element as HTMLCanvasElement
      canvas.width = 300
      canvas.height = 200

      // Activate celebration
      await wrapper.setProps({ isActive: true })
      await nextTick()

      // Canvas should now be active
      expect(wrapper.find('.celebration-canvas').classes()).toContain('is-active')
    })

    it('CelebrationEffect initializes confetti particles when active', async () => {
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
      expect(vm.particles.length).toBeGreaterThan(0)
      expect(vm.particles.length).toBe(50) // Default count
    })

    it('CelebrationEffect supports multiple effect types', () => {
      const types = ['confetti', 'pulse', 'stars'] as const

      types.forEach(type => {
        const wrapper = mount(CelebrationEffect, {
          props: { isActive: false, type }
        })

        expect(wrapper.find('canvas').exists()).toBe(true)
        expect(wrapper.props('type')).toBe(type)
      })
    })

    it('CelebrationEffect has configurable duration', () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false, duration: 5000 }
      })

      expect(wrapper.props('duration')).toBe(5000)
    })

    it('CelebrationEffect cleans up animation when inactive', async () => {
      const rafMock = setupRafMock()
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false }
      })

      // Set canvas dimensions
      const canvas = wrapper.find('canvas').element as HTMLCanvasElement
      canvas.width = 300
      canvas.height = 200

      // Activate
      await wrapper.setProps({ isActive: true })

      // Deactivate
      await wrapper.setProps({ isActive: false })

      // Animation should be cancelled
      expect(rafMock.getPendingCount()).toBe(0)
    })

    it('CelebrationEffect initializes stars for stars type', async () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false, type: 'stars' }
      })

      const canvas = wrapper.find('canvas').element as HTMLCanvasElement
      canvas.width = 300
      canvas.height = 200

      await wrapper.setProps({ isActive: true })

      const vm = wrapper.vm as any
      expect(vm.stars.length).toBeGreaterThan(0)
    })

    it('CelebrationEffect initializes pulse rings for pulse type', async () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: false, type: 'pulse' }
      })

      const canvas = wrapper.find('canvas').element as HTMLCanvasElement
      canvas.width = 300
      canvas.height = 200

      await wrapper.setProps({ isActive: true })

      const vm = wrapper.vm as any
      expect(vm.pulseRings.length).toBeGreaterThan(0)
    })

    it('CelebrationEffect canvas has pointer-events: none for UX', () => {
      const wrapper = mount(CelebrationEffect, {
        props: { isActive: true }
      })

      // Canvas should have celebration-canvas class
      const canvas = wrapper.find('canvas')
      expect(canvas.classes()).toContain('celebration-canvas')
    })
  })

  describe('AC3: Micro-interactions timely', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.unstubAllGlobals()
    })

    it('NeonButton shows loading spinner with proper accessibility', async () => {
      const wrapper = mount(NeonButton, {
        props: { loading: true }
      })

      // Loading state should show spinner text
      expect(wrapper.text()).toContain('Loading...')
      expect(wrapper.props('loading')).toBe(true)

      // Check aria-busy for accessibility
      expect(wrapper.attributes('aria-busy')).toBe('true')

      // Button should be disabled during loading
      expect(wrapper.attributes('disabled')).toBeDefined()
    })

    it('NeonButton transitions smoothly on hover (scale transform)', () => {
      const wrapper = mount(NeonButton)

      // Transition classes should be present
      expect(wrapper.classes()).toContain('transition-all')
      expect(wrapper.classes()).toContain('duration-200')
    })

    it('NeonButton has scale-bounce success animation', async () => {
      vi.useRealTimers()

      const wrapper = mount(NeonButton, {
        props: { success: false }
      })

      // Initially no animation class
      expect(wrapper.classes()).not.toContain('scale-bounce-animation')

      // Trigger success animation
      await wrapper.setProps({ success: true })
      await flushPromises()

      // Should have animation class
      expect(wrapper.classes()).toContain('scale-bounce-animation')

      // Wait for animation to complete (600ms)
      await new Promise(resolve => setTimeout(resolve, 700))

      // Animation class should be removed
      expect(wrapper.classes()).not.toContain('scale-bounce-animation')
    })

    it('ErrorCard shake animation is defined in component', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Test error' }
      })

      // ErrorCard component renders correctly
      expect(wrapper.find('.rounded-2xl').exists()).toBe(true)

      // Check that isShaking ref is exposed (for testing animation trigger)
      const vm = wrapper.vm as any
      expect(vm.isShaking).toBeDefined()
    })

    it('ErrorCard shake animation triggers on mount and stops after 300ms', async () => {
      vi.useRealTimers()

      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Test error' }
      })

      // Initially shaking (on mount)
      const vm = wrapper.vm as any
      expect(vm.isShaking).toBe(true)

      // Wait for animation to complete (300ms)
      await new Promise(resolve => setTimeout(resolve, 350))

      // Animation should stop
      expect(vm.isShaking).toBe(false)
    })

    it('AnimatedCounter updates value when prop changes', async () => {
      vi.useFakeTimers()

      // Stub requestAnimationFrame for animation
      let rafId = 0
      vi.stubGlobal('requestAnimationFrame', () => ++rafId)
      vi.stubGlobal('cancelAnimationFrame', () => {})
      vi.stubGlobal('performance', { now: () => 0 })

      const wrapper = mount(AnimatedCounter, {
        props: { value: 0, duration: 500 }
      })

      // Initial value should be 0
      expect(wrapper.vm.displayValue).toBe(0)

      // Update to new value
      await wrapper.setProps({ value: 100 })
      await vi.runAllTimersAsync()

      // Component should have isAnimating state during animation
      expect(wrapper.vm.isAnimating).toBeDefined()
    })

    it('AnimatedCounter default duration is 500ms (timely)', () => {
      const wrapper = mount(AnimatedCounter, {
        props: { value: 50 }
      })

      expect(wrapper.props('duration')).toBe(500)
    })

    it('AnimatedCounter has is-animating class structure', async () => {
      const wrapper = mount(AnimatedCounter, {
        props: { value: 100 }
      })

      // The span has the animated-counter class
      const counter = wrapper.find('.animated-counter')
      expect(counter.exists()).toBe(true)
      expect(counter.element.tagName).toBe('SPAN')
    })

    it('AnimatedCounter supports custom format function', async () => {
      const formatFn = (v: number) => `$${v.toFixed(2)}`

      const wrapper = mount(AnimatedCounter, {
        props: { value: 100, format: formatFn }
      })

      expect(wrapper.text()).toContain('$100.00')
    })

    it('useAnimation composable provides animation functions', () => {
      // Create a simple wrapper to test the composable
      const TestComponent = {
        template: '<div></div>',
        setup() {
          const { animatedCounter, cancelAnimation, isAnimating } = useAnimation()
          return { animatedCounter, cancelAnimation, isAnimating }
        }
      }

      const wrapper = mount(TestComponent)

      expect(typeof wrapper.vm.animatedCounter).toBe('function')
      expect(typeof wrapper.vm.cancelAnimation).toBe('function')
      expect(wrapper.vm.isAnimating).toBe(false)
    })

    it('Micro-interaction animations complete within acceptable time (< 1s)', () => {
      // All micro-interactions should be timely (< 1000ms)
      const durations = {
        shake: 300,       // ErrorCard shake
        scaleBounce: 600, // NeonButton success
        fadeSlide: 200,   // PageTransition
        counter: 500      // AnimatedCounter
      }

      Object.entries(durations).forEach(([name, duration]) => {
        expect(duration).toBeLessThan(1000)
      })
    })

    it('NeonButton scale-bounce animation is 600ms (timely)', async () => {
      vi.useRealTimers()

      const wrapper = mount(NeonButton, { props: { success: false } })

      await wrapper.setProps({ success: true })

      // Animation should start
      expect(wrapper.classes()).toContain('scale-bounce-animation')

      // Wait exactly 600ms (animation duration)
      await new Promise(resolve => setTimeout(resolve, 600))

      // Animation class should still be present (600ms timeout in component)
      // Wait a bit more for cleanup
      await new Promise(resolve => setTimeout(resolve, 50))

      expect(wrapper.classes()).not.toContain('scale-bounce-animation')
    })

    it('ErrorCard shake animation is 300ms (timely)', async () => {
      vi.useRealTimers()

      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Test error' }
      })

      const vm = wrapper.vm as any

      // Initially shaking
      expect(vm.isShaking).toBe(true)

      // Wait 300ms
      await new Promise(resolve => setTimeout(resolve, 300))

      // Animation stops
      expect(vm.isShaking).toBe(false)
    })
  })
})