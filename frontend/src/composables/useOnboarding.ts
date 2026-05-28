// frontend/src/composables/useOnboarding.ts
import { ref, computed } from 'vue'
import { useOnboardingStore } from '@/stores/onboarding'
import type { OnboardingStep, TourStep } from '@/types/onboarding'
import { ONBOARDING_STORAGE_KEY, DEFAULT_ONBOARDING_STATE } from '@/types/onboarding'

/**
 * Tour steps configuration
 */
export const TOUR_STEPS: TourStep[] = [
  {
    step: 1,
    title: 'Welcome to XhsGrowthAgent',
    description: 'This tool helps you automate content growth on Xiaohongshu. Let\'s take a quick tour to get you started.',
    targetElement: '#app',
    position: 'top',
  },
  {
    step: 2,
    title: 'Workflow Dashboard',
    description: 'Here you can start, monitor, and control your content growth workflow. The progress bar shows the current phase.',
    targetElement: '.workflow-header',
    position: 'bottom',
  },
  {
    step: 3,
    title: 'Review Panel',
    description: 'When the workflow pauses for review, you can approve or revise the generated content here. Use keyboard shortcuts for quick actions.',
    targetElement: '.review-panel',
    position: 'left',
  },
]

/**
 * Composable for onboarding tour functionality
 */
export function useOnboarding() {
  const store = useOnboardingStore()

  // Local state for tour content
  const tourSteps = ref<TourStep[]>(TOUR_STEPS)
  const isVisible = ref(false)

  // Computed
  const currentTourStep = computed(() => {
    return tourSteps.value.find(s => s.step === store.currentStep)
  })

  const isFirstStep = computed(() => store.currentStep === 1)
  const isLastStep = computed(() => store.currentStep === 3)
  const hasCompletedOnboarding = computed(() => store.hasCompleted)

  /**
   * Check localStorage for onboarding state
   */
  function checkLocalStorage(): boolean {
    try {
      const stored = localStorage.getItem(ONBOARDING_STORAGE_KEY)
      if (stored) {
        const state = JSON.parse(stored)
        return state.has_completed_onboarding === true
      }
    } catch (e) {
      console.warn('Failed to check localStorage for onboarding:', e)
    }
    return false
  }

  /**
   * Get current step from localStorage
   */
  function getCurrentStep(): OnboardingStep {
    try {
      const stored = localStorage.getItem(ONBOARDING_STORAGE_KEY)
      if (stored) {
        const state = JSON.parse(stored)
        if (state.current_step && [1, 2, 3].includes(state.current_step)) {
          return state.current_step as OnboardingStep
        }
      }
    } catch (e) {
      console.warn('Failed to get current step from localStorage:', e)
    }
    return 1
  }

  /**
   * Advance to the next step
   */
  function advanceStep(): void {
    store.nextStep()

    // If completed, hide tour
    if (store.hasCompleted) {
      isVisible.value = false
    }
  }

  /**
   * Start the onboarding tour
   */
  function startTour(): void {
    if (store.hasCompleted) return
    store.startTour()
    isVisible.value = true
  }

  /**
   * Skip the onboarding tour
   */
  function skipTour(): void {
    store.skipTour()
    isVisible.value = false
  }

  /**
   * Complete the onboarding tour
   */
  function completeTour(): void {
    store.completeTour()
    isVisible.value = false
  }

  /**
   * Go to a specific step
   */
  function goToStep(step: OnboardingStep): void {
    store.goToStep(step)
  }

  /**
   * Get tour step by step number
   */
  function getTourStep(step: OnboardingStep): TourStep | undefined {
    return tourSteps.value.find(s => s.step === step)
  }

  /**
   * Initialize onboarding - check if user needs to see tour
   */
  function initOnboarding(): void {
    const completed = checkLocalStorage()
    if (!completed) {
      // User hasn't completed onboarding, show tour
      startTour()
    }
  }

  return {
    // State
    tourSteps,
    isVisible,
    // Computed
    currentTourStep,
    isFirstStep,
    isLastStep,
    hasCompletedOnboarding,
    // Actions
    checkLocalStorage,
    getCurrentStep,
    advanceStep,
    startTour,
    skipTour,
    completeTour,
    goToStep,
    getTourStep,
    initOnboarding,
    // Constants
    TOUR_STEPS,
  }
}