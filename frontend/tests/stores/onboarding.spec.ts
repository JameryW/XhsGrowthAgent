// frontend/tests/stores/onboarding.spec.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useOnboardingStore } from '@/stores/onboarding'
import { ONBOARDING_STORAGE_KEY } from '@/types/onboarding'

// Mock localStorage for happy-dom environment
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
    get length() { return Object.keys(store).length },
    key: (index: number) => Object.keys(store)[index] || null,
  }
})()

describe('onboarding store', () => {
  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
    // Stub localStorage with our mock
    vi.stubGlobal('localStorage', localStorageMock)
    // Clear localStorage mock before each test
    localStorageMock.clear()
  })

  afterEach(() => {
    // Clean up localStorage mock after each test
    localStorageMock.clear()
    vi.unstubAllGlobals()
  })

  describe('initial state', () => {
    it('has correct default values when localStorage is empty', () => {
      const store = useOnboardingStore()

      expect(store.isActive).toBe(false)
      expect(store.currentStep).toBe(1)
      expect(store.hasCompleted).toBe(false)
    })

    it('loads state from localStorage', () => {
      // Pre-populate localStorage
      localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: true,
        current_step: 2,
        completed_at: '2026-05-28T00:00:00Z',
      }))

      const store = useOnboardingStore()

      expect(store.hasCompleted).toBe(true)
      expect(store.currentStep).toBe(2)
    })
  })

  describe('startTour', () => {
    it('sets isActive to true', () => {
      const store = useOnboardingStore()

      store.startTour()

      expect(store.isActive).toBe(true)
    })

    it('sets currentStep to 1', () => {
      const store = useOnboardingStore()
      store.currentStep = 2

      store.startTour()

      expect(store.currentStep).toBe(1)
    })

    it('does not start if already completed', () => {
      const store = useOnboardingStore()
      store.hasCompleted = true

      store.startTour()

      expect(store.isActive).toBe(false)
    })
  })

  describe('nextStep', () => {
    it('advances from step 1 to 2', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.nextStep()

      expect(store.currentStep).toBe(2)
    })

    it('advances from step 2 to 3', () => {
      const store = useOnboardingStore()
      store.startTour()
      store.nextStep()

      store.nextStep()

      expect(store.currentStep).toBe(3)
    })

    it('completes tour when advancing from step 3', () => {
      const store = useOnboardingStore()
      store.startTour()
      store.currentStep = 3

      store.nextStep()

      expect(store.hasCompleted).toBe(true)
      expect(store.isActive).toBe(false)
    })

    it('does nothing when tour is not active', () => {
      const store = useOnboardingStore()
      store.isActive = false
      store.currentStep = 1

      store.nextStep()

      expect(store.currentStep).toBe(1)
    })

    it('saves current step to localStorage', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.nextStep()

      const stored = JSON.parse(localStorage.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.current_step).toBe(2)
    })
  })

  describe('skipTour', () => {
    it('sets isActive to false', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.skipTour()

      expect(store.isActive).toBe(false)
    })

    it('sets hasCompleted to true', () => {
      const store = useOnboardingStore()

      store.skipTour()

      expect(store.hasCompleted).toBe(true)
    })

    it('saves completion state to localStorage', () => {
      const store = useOnboardingStore()

      store.skipTour()

      const stored = JSON.parse(localStorage.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.has_completed_onboarding).toBe(true)
      expect(stored.skipped).toBe(true)
      expect(stored.completed_at).toBeDefined()
    })
  })

  describe('completeTour', () => {
    it('sets isActive to false', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.completeTour()

      expect(store.isActive).toBe(false)
    })

    it('sets hasCompleted to true', () => {
      const store = useOnboardingStore()

      store.completeTour()

      expect(store.hasCompleted).toBe(true)
    })

    it('sets currentStep to 3', () => {
      const store = useOnboardingStore()
      store.currentStep = 1

      store.completeTour()

      expect(store.currentStep).toBe(3)
    })

    it('saves completion state to localStorage', () => {
      const store = useOnboardingStore()

      store.completeTour()

      const stored = JSON.parse(localStorage.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.has_completed_onboarding).toBe(true)
      expect(stored.current_step).toBe(3)
      expect(stored.skipped).toBe(false)
      expect(stored.completed_at).toBeDefined()
    })
  })

  describe('computed properties', () => {
    it('isOnboardingActive returns true when active and not completed', () => {
      const store = useOnboardingStore()
      store.startTour()

      expect(store.isOnboardingActive).toBe(true)
    })

    it('isOnboardingActive returns false when completed', () => {
      const store = useOnboardingStore()
      store.completeTour()

      expect(store.isOnboardingActive).toBe(false)
    })

    it('progressPercent returns 0 when at step 1', () => {
      const store = useOnboardingStore()
      store.currentStep = 1
      store.hasCompleted = false

      expect(store.progressPercent).toBe(33.33333333333333)
    })

    it('progressPercent returns 100 when completed', () => {
      const store = useOnboardingStore()
      store.completeTour()

      expect(store.progressPercent).toBe(100)
    })

    it('progressPercent returns correct percentage at step 2', () => {
      const store = useOnboardingStore()
      store.currentStep = 2
      store.hasCompleted = false

      expect(store.progressPercent).toBe(66.66666666666666)
    })
  })

  describe('resetOnboarding', () => {
    it('clears all state', () => {
      const store = useOnboardingStore()
      store.startTour()
      store.completeTour()

      store.resetOnboarding()

      expect(store.isActive).toBe(false)
      expect(store.currentStep).toBe(1)
      expect(store.hasCompleted).toBe(false)
    })

    it('removes localStorage entry', () => {
      const store = useOnboardingStore()
      store.completeTour()

      store.resetOnboarding()

      expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe(null)
    })
  })

  describe('goToStep', () => {
    it('sets current step to specified value', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.goToStep(2)

      expect(store.currentStep).toBe(2)
    })

    it('does nothing when tour is not active', () => {
      const store = useOnboardingStore()
      store.isActive = false

      store.goToStep(2)

      expect(store.currentStep).toBe(1)
    })

    it('saves step to localStorage', () => {
      const store = useOnboardingStore()
      store.startTour()

      store.goToStep(3)

      const stored = JSON.parse(localStorage.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.current_step).toBe(3)
    })
  })
})