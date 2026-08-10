// frontend/src/composables/useAnimation.ts
import { ref, onUnmounted } from 'vue'
import { prefersReducedMotion } from './useReducedMotion'

/**
 * Composable for animation utilities
 * Provides smooth counter animation using requestAnimationFrame
 */
export function useAnimation() {
  const animationFrameId = ref<number | null>(null)
  const isAnimating = ref(false)
  // A generation token makes cancellation safe across browser implementations
  // where cancelAnimationFrame can race with an already-dispatched frame.
  let animationGeneration = 0

  /**
   * Animated counter using requestAnimationFrame
   * Smoothly transitions from start to end value over duration
   * @param start - Starting value
   * @param end - Ending value
   * @param duration - Animation duration in milliseconds
   * @param onUpdate - Callback function called on each frame with current value
   * @returns Promise that resolves when animation completes
   */
  const animatedCounter = (
    start: number,
    end: number,
    duration: number,
    onUpdate: (currentValue: number) => void
  ): Promise<void> => {
    return new Promise((resolve) => {
      // Invalidate any existing animation. The old callback may already be in
      // the event queue, so avoid cancelling a potentially stale native timer.
      animationGeneration += 1
      const generation = animationGeneration

      isAnimating.value = true
      const startTime = performance.now()
      const change = end - start

      const animate = (currentTime: number) => {
        if (generation !== animationGeneration) {
          resolve()
          return
        }

        const elapsed = currentTime - startTime
        const progress = Math.min(elapsed / duration, 1)

        // Use ease-out cubic for smoother feel
        const easeOut = 1 - Math.pow(1 - progress, 3)
        const currentValue = start + change * easeOut

        onUpdate(Math.round(currentValue))

        if (progress < 1) {
          animationFrameId.value = requestAnimationFrame(animate)
        } else {
          isAnimating.value = false
          animationFrameId.value = null
          resolve()
        }
      }

      // Handle zero duration case
      if (duration === 0) {
        onUpdate(end)
        isAnimating.value = false
        resolve()
        return
      }

      // INF-05: respect prefers-reduced-motion — jump to the final value
      // instead of animating.
      if (prefersReducedMotion.value) {
        onUpdate(end)
        isAnimating.value = false
        resolve()
        return
      }

      animationFrameId.value = requestAnimationFrame(animate)
    })
  }

  /**
   * Cancel any ongoing animation
   */
  const cancelAnimation = () => {
    animationGeneration += 1
    animationFrameId.value = null
    isAnimating.value = false
  }

  // Cleanup on component unmount
  onUnmounted(() => {
    cancelAnimation()
  })

  return {
    animatedCounter,
    cancelAnimation,
    isAnimating
  }
}

/**
 * Standalone animated counter function (for use outside Vue components)
 * Does not use lifecycle hooks
 */
export function animatedCounter(
  start: number,
  end: number,
  duration: number,
  onUpdate: (currentValue: number) => void
): Promise<void> {
  return new Promise((resolve) => {
    // Keep the standalone helper consistent with useAnimation(): callers
    // outside a component must also respect the user's motion preference.
    if (duration === 0 || prefersReducedMotion.value) {
      onUpdate(end)
      resolve()
      return
    }

    const startTime = performance.now()
    const change = end - start
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)

      const easeOut = 1 - Math.pow(1 - progress, 3)
      const currentValue = start + change * easeOut

      onUpdate(Math.round(currentValue))

      if (progress < 1) {
        requestAnimationFrame(animate)
      } else {
        resolve()
      }
    }

    requestAnimationFrame(animate)
  })
}
