// frontend/src/stores/onboarding.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { OnboardingStep, OnboardingState } from '@/types/onboarding'
import { ONBOARDING_STORAGE_KEY, DEFAULT_ONBOARDING_STATE } from '@/types/onboarding'

/**
 * Onboarding store for managing tour state and localStorage persistence
 */
export const useOnboardingStore = defineStore('onboarding', () => {
  // State
  const isActive = ref(false)
  const currentStep = ref<OnboardingStep>(1)
  const hasCompleted = ref(false)

  /**
   * Read state from localStorage without modifying store state
   */
  function readFromStorage(): OnboardingState {
    try {
      const stored = localStorage.getItem(ONBOARDING_STORAGE_KEY)
      if (stored) {
        return JSON.parse(stored) as OnboardingState
      }
    } catch (e) {
      console.warn('Failed to read onboarding state from localStorage:', e)
    }
    return DEFAULT_ONBOARDING_STATE
  }

  /**
   * Load state from localStorage and update store state
   */
  function loadFromStorage(): OnboardingState {
    const state = readFromStorage()
    hasCompleted.value = state.has_completed_onboarding
    if (state.current_step) {
      currentStep.value = state.current_step
    }
    return state
  }

  /**
   * Save state to localStorage
   */
  function saveToStorage(state: Partial<OnboardingState>): void {
    try {
      const existing = readFromStorage()
      const newState: OnboardingState = {
        ...existing,
        ...state,
      }
      localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(newState))
    } catch (e) {
      console.warn('Failed to save onboarding state to localStorage:', e)
    }
  }

  // Initialize from localStorage on store creation
  loadFromStorage()

  // Computed
  const isOnboardingActive = computed(() => isActive.value && !hasCompleted.value)
  const progressPercent = computed(() => {
    if (hasCompleted.value) return 100
    return (currentStep.value / 3) * 100
  })

  // Actions
  /**
   * Start the onboarding tour
   */
  function startTour(): void {
    if (hasCompleted.value) return
    isActive.value = true
    currentStep.value = 1
  }

  /**
   * Advance to the next step
   */
  function nextStep(): void {
    if (!isActive.value) return
    if (currentStep.value < 3) {
      currentStep.value = (currentStep.value + 1) as OnboardingStep
      saveToStorage({ current_step: currentStep.value })
    } else {
      // Automatically complete when reaching the last step
      completeTour()
    }
  }

  /**
   * Skip the onboarding tour
   */
  function skipTour(): void {
    isActive.value = false
    hasCompleted.value = true
    saveToStorage({
      has_completed_onboarding: true,
      skipped: true,
      completed_at: new Date().toISOString(),
    })
  }

  /**
   * Complete the onboarding tour
   */
  function completeTour(): void {
    isActive.value = false
    hasCompleted.value = true
    currentStep.value = 3
    saveToStorage({
      has_completed_onboarding: true,
      current_step: 3,
      skipped: false,
      completed_at: new Date().toISOString(),
    })
  }

  /**
   * Reset onboarding state (for testing or re-onboarding)
   */
  function resetOnboarding(): void {
    isActive.value = false
    currentStep.value = 1
    hasCompleted.value = false
    localStorage.removeItem(ONBOARDING_STORAGE_KEY)
  }

  /**
   * Go to a specific step
   */
  function goToStep(step: OnboardingStep): void {
    if (!isActive.value) return
    currentStep.value = step
    saveToStorage({ current_step: step })
  }

  return {
    // State
    isActive,
    currentStep,
    hasCompleted,
    // Computed
    isOnboardingActive,
    progressPercent,
    // Actions
    startTour,
    nextStep,
    skipTour,
    completeTour,
    resetOnboarding,
    goToStep,
    loadFromStorage,
    saveToStorage,
  }
})