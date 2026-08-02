import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SkeletonLoader from '@/components/SkeletonLoader.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'
import ReviewSkeleton from '@/components/skeletons/ReviewSkeleton.vue'
import AnalyticsSkeleton from '@/components/skeletons/AnalyticsSkeleton.vue'
import { useLoading } from '@/composables/useLoading'
import type { WorkflowPhase } from '@/types'

/**
 * Theme 1 Acceptance Tests
 *
 * AC1: All views use unified Skeleton components (Review, Analytics)
 * AC2: Progress bar updates realtime with correct colors (phase colors mapping)
 * AC3: Loading state does not block user operation perception (cancel button works)
 */
describe('Theme 1 Acceptance Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('AC1: All views use unified Skeleton components', () => {
    it('ReviewSkeleton renders with correct structure', () => {
      const wrapper = mount(ReviewSkeleton)

      // Verify skeleton structure matches Review view layout
      expect(wrapper.find('.relative.space-y-5').exists()).toBe(true)

      // Status bar skeleton
      expect(wrapper.find('.w-14.h-14.rounded-xl.bg-slate-200.animate-pulse').exists()).toBe(true)

      // Content preview grid (copy content + visual plan)
      const gridItems = wrapper.findAll('.grid.grid-cols-1.lg\\:grid-cols-2 > div')
      expect(gridItems.length).toBe(2)

      // Action buttons skeleton (3 buttons)
      const buttonsSkeleton = wrapper.findAll('.grid.grid-cols-1.sm\\:grid-cols-3.gap-3.mb-4 > div')
      expect(buttonsSkeleton.length).toBe(3)

      // All skeleton elements use animate-pulse
      expect(wrapper.findAll('.animate-pulse').length).toBeGreaterThan(0)
    })

    it('AnalyticsSkeleton renders with correct structure', () => {
      const wrapper = mount(AnalyticsSkeleton)

      // Verify skeleton structure matches Analytics view layout
      expect(wrapper.find('.relative.space-y-6').exists()).toBe(true)

      // Header skeleton with refresh + 3 period buttons
      expect(wrapper.find('.w-14.h-14.rounded-xl.bg-slate-200.animate-pulse').exists()).toBe(true)
      const headerButtons = wrapper.findAll('.h-8.w-16.rounded.bg-slate-200.animate-pulse')
      expect(headerButtons.length).toBe(4)

      // Metrics grid (5 metric cards, same grid classes as the live view)
      const metricsGrid = wrapper.find('.grid.grid-cols-2.sm\\:grid-cols-3.xl\\:grid-cols-5')
      expect(metricsGrid.exists()).toBe(true)
      expect(metricsGrid.findAll(':scope > div').length).toBe(5)

      // Charts skeleton (2 charts, same 220px height as the live charts)
      const chartSkeletons = wrapper.findAll('.h-\\[220px\\].rounded-lg.bg-slate-100.animate-pulse')
      expect(chartSkeletons.length).toBe(2)

      // All skeleton elements use animate-pulse
      expect(wrapper.findAll('.animate-pulse').length).toBeGreaterThan(0)
    })

    it('SkeletonLoader provides unified base component for all skeleton types', () => {
      // Test text skeleton
      const textWrapper = mount(SkeletonLoader, { props: { type: 'text', lines: 3 } })
      expect(textWrapper.findAll('.shimmer-animation')).toHaveLength(3)

      // Test card skeleton
      const cardWrapper = mount(SkeletonLoader, { props: { type: 'card', width: 300 } })
      expect(cardWrapper.find('.shimmer-animation').exists()).toBe(true)

      // Test avatar skeleton
      const avatarWrapper = mount(SkeletonLoader, { props: { type: 'avatar', size: 48 } })
      expect(avatarWrapper.find('.shimmer-animation').exists()).toBe(true)

      // Test list skeleton
      const listWrapper = mount(SkeletonLoader, { props: { type: 'list' } })
      expect(listWrapper.findAll('.shimmer-animation').length).toBeGreaterThan(0)

      // All types use the same shimmer-animation class
      expect(textWrapper.find('.shimmer-animation').classes()).toContain('shimmer-animation')
      expect(cardWrapper.find('.shimmer-animation').classes()).toContain('shimmer-animation')
      expect(avatarWrapper.find('.shimmer-animation').classes()).toContain('shimmer-animation')
    })
  })

  describe('AC2: Progress bar updates realtime with correct colors', () => {
    it('useLoading maps each workflow phase to its display color', () => {
      const { phaseToColor } = useLoading()

      // Test color mapping for all phases
      const phaseColorTests: Array<{ phase: WorkflowPhase; expectedColor: string }> = [
        { phase: 'idle', expectedColor: '#94a3b8' },      // slate-400
        { phase: 'scouting', expectedColor: '#f43f5e' },  // rose-500
        { phase: 'planning', expectedColor: '#8b5cf6' },  // violet-500
        { phase: 'creating', expectedColor: '#14b8a6' },  // teal-500
        { phase: 'reviewing', expectedColor: '#f59e0b' }, // amber-500
        { phase: 'publishing', expectedColor: '#3b82f6' }, // blue-500
        { phase: 'analyzing', expectedColor: '#22c55e' }, // green-500
        { phase: 'engaging', expectedColor: '#22c55e' },  // green-500
        { phase: 'completed', expectedColor: '#10b981' }, // emerald-500
        { phase: 'error', expectedColor: '#f43f5e' },     // rose-500
        { phase: 'cancelled', expectedColor: '#94a3b8' }, // slate-400
      ]

      phaseColorTests.forEach(({ phase, expectedColor }) => {
        expect(phaseToColor(phase)).toBe(expectedColor)
      })
    })

    it('useLoading composable provides correct phase-to-percent mapping', () => {
      const { phaseToPercent } = useLoading()

      const phasePercentTests: Array<{ phase: WorkflowPhase; expectedPercent: number }> = [
        { phase: 'idle', expectedPercent: 0 },
        { phase: 'scouting', expectedPercent: 10 },
        { phase: 'planning', expectedPercent: 20 },
        { phase: 'creating', expectedPercent: 40 },
        { phase: 'reviewing', expectedPercent: 60 },
        { phase: 'publishing', expectedPercent: 80 },
        { phase: 'analyzing', expectedPercent: 90 },
        { phase: 'engaging', expectedPercent: 95 },
        { phase: 'completed', expectedPercent: 100 },
        { phase: 'error', expectedPercent: 0 },
        { phase: 'cancelled', expectedPercent: 0 },
      ]

      phasePercentTests.forEach(({ phase, expectedPercent }) => {
        expect(phaseToPercent(phase)).toBe(expectedPercent)
      })
    })
  })

  describe('AC3: Loading state does not block user operation perception', () => {
    it('LoadingOverlay shows cancel button by default (canCancel=true)', () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true }
      })

      expect(wrapper.find('button').exists()).toBe(true)
      expect(wrapper.text()).toContain('取消操作')
    })

    it('LoadingOverlay emits cancel event when cancel button is clicked', async () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true }
      })

      const cancelButton = wrapper.find('button')
      await cancelButton.trigger('click')

      expect(wrapper.emitted('cancel')).toBeTruthy()
      expect(wrapper.emitted('cancel').length).toBe(1)
    })

    it('LoadingOverlay cancel button is accessible', async () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true }
      })

      const cancelButton = wrapper.find('button')
      expect(cancelButton.attributes('aria-label')).toBe('取消操作')
      expect(cancelButton.text()).toContain('取消操作')
    })

    it('LoadingOverlay hides cancel button when canCancel=false', () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true, canCancel: false }
      })

      expect(wrapper.find('button').exists()).toBe(false)
    })

    it('LoadingOverlay allows user to interact with cancel button while loading', () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true, message: '正在发布内容...', canCancel: true }
      })

      // Verify overlay is visible
      expect(wrapper.find('.loading-overlay').exists()).toBe(true)

      // Verify spinner is animating
      expect(wrapper.find('.rotate-animation').exists()).toBe(true)

      // Verify message is displayed
      expect(wrapper.text()).toContain('正在发布内容...')

      // Verify cancel button is present and clickable (not disabled)
      const cancelButton = wrapper.find('button')
      expect(cancelButton.exists()).toBe(true)
      expect(cancelButton.attributes('disabled')).toBeUndefined()

      // Simulate cancel click - should emit event
      cancelButton.trigger('click')
      expect(wrapper.emitted('cancel')).toBeTruthy()
    })

    it('LoadingOverlay has proper modal dialog accessibility', () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true }
      })

      // Verify role="dialog" and aria-modal="true"
      const overlay = wrapper.find('[role="dialog"]')
      expect(overlay.exists()).toBe(true)
      expect(overlay.attributes('aria-modal')).toBe('true')

      // Verify aria-labelledby points to message
      expect(overlay.attributes('aria-labelledby')).toBe('loading-message')

      // Verify message element has matching id
      const message = wrapper.find('#loading-message')
      expect(message.exists()).toBe(true)
    })

    it('LoadingOverlay backdrop does not block cancel button clicks', () => {
      const wrapper = mount(LoadingOverlay, {
        props: { isVisible: true }
      })

      // Backdrop exists but is separate from content
      expect(wrapper.find('.bg-slate-900\\/40').exists()).toBe(true)

      // Content container exists above backdrop (relative positioning)
      const contentContainer = wrapper.find('.bg-white.rounded-2xl')
      expect(contentContainer.exists()).toBe(true)
      expect(contentContainer.classes()).toContain('relative')

      // Cancel button is in content container, not in backdrop
      const cancelButton = wrapper.find('button')
      expect(cancelButton.element.parentElement?.classList.contains('bg-white')).toBe(true)
    })
  })
})
