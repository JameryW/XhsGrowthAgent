// frontend/tests/composables/useOnboarding.spec.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useOnboarding, TOUR_STEPS } from '@/composables/useOnboarding'
import { ONBOARDING_STORAGE_KEY } from '@/types/onboarding'
import { useOnboardingStore } from '@/stores/onboarding'

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

describe('useOnboarding', () => {
  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
    // Stub localStorage with our mock
    vi.stubGlobal('localStorage', localStorageMock)
    // Clear localStorage mock before each test
    localStorageMock.clear()
  })

  afterEach(() => {
    localStorageMock.clear()
    vi.unstubAllGlobals()
  })

  describe('TOUR_STEPS constant', () => {
    it('has 3 steps', () => {
      expect(TOUR_STEPS.length).toBe(3)
    })

    it('has step 1 as welcome', () => {
      const step1 = TOUR_STEPS.find(s => s.step === 1)
      expect(step1).toBeDefined()
      expect(step1?.title).toBe('Welcome to XhsGrowthAgent')
      expect(step1?.targetElement).toBe('#app')
    })

    it('has step 2 as dashboard', () => {
      const step2 = TOUR_STEPS.find(s => s.step === 2)
      expect(step2).toBeDefined()
      expect(step2?.title).toBe('Workflow Dashboard')
      expect(step2?.targetElement).toBe('.workflow-header')
    })

    it('has step 3 as review panel', () => {
      const step3 = TOUR_STEPS.find(s => s.step === 3)
      expect(step3).toBeDefined()
      expect(step3?.title).toBe('Review Panel')
      expect(step3?.targetElement).toBe('.review-panel')
    })

    it('each step has required properties', () => {
      TOUR_STEPS.forEach(step => {
        expect(step.step).toBeDefined()
        expect(step.title).toBeDefined()
        expect(step.description).toBeDefined()
        expect(step.position).toBeDefined()
      })
    })
  })

  describe('checkLocalStorage', () => {
    it('returns false when localStorage is empty', () => {
      const onboarding = useOnboarding()

      expect(onboarding.checkLocalStorage()).toBe(false)
    })

    it('returns true when has_completed_onboarding is true', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: true,
      }))

      const onboarding = useOnboarding()

      expect(onboarding.checkLocalStorage()).toBe(true)
    })

    it('returns false when has_completed_onboarding is false', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: false,
      }))

      const onboarding = useOnboarding()

      expect(onboarding.checkLocalStorage()).toBe(false)
    })
  })

  describe('getCurrentStep', () => {
    it('returns 1 when localStorage is empty', () => {
      const onboarding = useOnboarding()

      expect(onboarding.getCurrentStep()).toBe(1)
    })

    it('returns stored step value', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        current_step: 2,
      }))

      const onboarding = useOnboarding()

      expect(onboarding.getCurrentStep()).toBe(2)
    })

    it('returns 1 when stored value is invalid', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        current_step: 'invalid',
      }))

      const onboarding = useOnboarding()

      expect(onboarding.getCurrentStep()).toBe(1)
    })
  })

  describe('advanceStep', () => {
    it('advances from step 1 to 2', () => {
      const onboarding = useOnboarding()
      const store = useOnboardingStore()
      onboarding.startTour()

      onboarding.advanceStep()

      expect(store.currentStep).toBe(2)
    })

    it('advances from step 2 to 3', () => {
      const onboarding = useOnboarding()
      const store = useOnboardingStore()
      onboarding.startTour()

      // Advance to step 2 first
      onboarding.advanceStep()
      expect(store.currentStep).toBe(2)

      // Then advance to step 3
      onboarding.advanceStep()

      expect(store.currentStep).toBe(3)
    })
  })

  describe('startTour', () => {
    it('sets isVisible to true', () => {
      const onboarding = useOnboarding()

      onboarding.startTour()

      expect(onboarding.isVisible.value).toBe(true)
    })

    it('does not start if already completed', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: true,
      }))

      const onboarding = useOnboarding()

      onboarding.startTour()

      expect(onboarding.isVisible.value).toBe(false)
    })
  })

  describe('skipTour', () => {
    it('sets isVisible to false', () => {
      const onboarding = useOnboarding()
      onboarding.startTour()

      onboarding.skipTour()

      expect(onboarding.isVisible.value).toBe(false)
    })

    it('saves to localStorage', () => {
      const onboarding = useOnboarding()

      onboarding.skipTour()

      const stored = JSON.parse(localStorageMock.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.has_completed_onboarding).toBe(true)
      expect(stored.skipped).toBe(true)
    })
  })

  describe('completeTour', () => {
    it('sets isVisible to false', () => {
      const onboarding = useOnboarding()
      onboarding.startTour()

      onboarding.completeTour()

      expect(onboarding.isVisible.value).toBe(false)
    })

    it('saves to localStorage', () => {
      const onboarding = useOnboarding()

      onboarding.completeTour()

      const stored = JSON.parse(localStorageMock.getItem(ONBOARDING_STORAGE_KEY) || '{}')
      expect(stored.has_completed_onboarding).toBe(true)
      expect(stored.current_step).toBe(3)
    })
  })

  describe('computed properties', () => {
    it('currentTourStep returns current step data', () => {
      const onboarding = useOnboarding()
      onboarding.startTour()

      expect(onboarding.currentTourStep.value?.step).toBe(1)
      expect(onboarding.currentTourStep.value?.title).toBe('Welcome to XhsGrowthAgent')
    })

    it('isFirstStep returns true on step 1', () => {
      const onboarding = useOnboarding()
      onboarding.startTour()

      expect(onboarding.isFirstStep.value).toBe(true)
    })

    it('isLastStep returns true on step 3', () => {
      const onboarding = useOnboarding()
      const store = useOnboardingStore()
      onboarding.startTour()

      // Advance to step 3
      store.goToStep(3)

      expect(onboarding.isLastStep.value).toBe(true)
    })

    it('hasCompletedOnboarding reflects store state', () => {
      const onboarding = useOnboarding()

      expect(onboarding.hasCompletedOnboarding.value).toBe(false)
    })
  })

  describe('getTourStep', () => {
    it('returns step data for valid step', () => {
      const onboarding = useOnboarding()

      const step = onboarding.getTourStep(2)

      expect(step?.step).toBe(2)
      expect(step?.title).toBe('Workflow Dashboard')
    })

    it('returns undefined for invalid step', () => {
      const onboarding = useOnboarding()

      const step = onboarding.getTourStep(5 as any)

      expect(step).toBeUndefined()
    })
  })

  describe('goToStep', () => {
    it('changes current step', () => {
      const onboarding = useOnboarding()
      const store = useOnboardingStore()
      onboarding.startTour()

      onboarding.goToStep(3)

      expect(store.currentStep).toBe(3)
    })
  })

  describe('initOnboarding', () => {
    it('starts tour when not completed', () => {
      const onboarding = useOnboarding()

      onboarding.initOnboarding()

      expect(onboarding.isVisible.value).toBe(true)
    })

    it('does not start tour when already completed', () => {
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: true,
      }))

      const onboarding = useOnboarding()

      onboarding.initOnboarding()

      expect(onboarding.isVisible.value).toBe(false)
    })
  })
})