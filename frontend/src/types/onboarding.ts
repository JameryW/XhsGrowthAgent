// frontend/src/types/onboarding.ts

/**
 * Onboarding step number (1, 2, or 3)
 */
export type OnboardingStep = 1 | 2 | 3

/**
 * Tour step configuration for the onboarding tour
 */
export interface TourStep {
  step: OnboardingStep
  title: string
  description: string
  targetElement?: string // CSS selector for the element to highlight
  position?: 'top' | 'bottom' | 'left' | 'right' // Tooltip position relative to target
}

/**
 * Onboarding state stored in localStorage
 */
export interface OnboardingState {
  has_completed_onboarding: boolean
  current_step?: OnboardingStep
  completed_at?: string // ISO timestamp
  skipped?: boolean
}

/**
 * Local storage key for onboarding state
 */
export const ONBOARDING_STORAGE_KEY = 'xhs_growth_onboarding'

/**
 * Default onboarding state
 */
export const DEFAULT_ONBOARDING_STATE: OnboardingState = {
  has_completed_onboarding: false,
}