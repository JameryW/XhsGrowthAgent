// frontend/src/composables/useAnimation.ts
import { ref, onUnmounted } from 'vue'

/**
 * Composable for animation utilities
 * Provides smooth counter animation using requestAnimationFrame
 */
export function useAnimation() {
  const animationFrameId = ref<number | null>(null)
  const isAnimating = ref(false)

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
      // Cancel any existing animation
      if (animationFrameId.value !== null) {
        cancelAnimationFrame(animationFrameId.value)
      }

      isAnimating.value = true
      const startTime = performance.now()
      const change = end - start

      const animate = (currentTime: number) => {
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

      animationFrameId.value = requestAnimationFrame(animate)
    })
  }

  /**
   * Cancel any ongoing animation
   */
  const cancelAnimation = () => {
    if (animationFrameId.value !== null) {
      cancelAnimationFrame(animationFrameId.value)
      animationFrameId.value = null
      isAnimating.value = false
    }
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
    if (duration === 0) {
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