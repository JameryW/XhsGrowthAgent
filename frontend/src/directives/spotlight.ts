import type { Directive } from 'vue'

interface SpotlightElement extends HTMLElement {
  __spotlightCleanup?: () => void
}

/**
 * v-spotlight — mouse-tracking radial highlight for cards.
 * Sets --sx/--sy on the element; styles live in `src/styles/public-pages.css`
 * (.spotlight-card / .spotlight-active). Skipped entirely for reduced motion
 * or coarse pointers, so touch devices pay nothing.
 */
export const vSpotlight: Directive<HTMLElement> = {
  mounted(el: SpotlightElement) {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const coarse = window.matchMedia('(pointer: coarse)').matches
    if (reduced || coarse) return

    el.classList.add('spotlight-card')
    let rafId = 0
    const onMove = (event: PointerEvent) => {
      if (rafId) return
      rafId = window.requestAnimationFrame(() => {
        rafId = 0
        const rect = el.getBoundingClientRect()
        el.style.setProperty('--sx', `${Math.round(event.clientX - rect.left)}px`)
        el.style.setProperty('--sy', `${Math.round(event.clientY - rect.top)}px`)
      })
    }
    const onEnter = () => el.classList.add('spotlight-active')
    const onLeave = () => el.classList.remove('spotlight-active')

    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerenter', onEnter)
    el.addEventListener('pointerleave', onLeave)
    el.__spotlightCleanup = () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerenter', onEnter)
      el.removeEventListener('pointerleave', onLeave)
      if (rafId) window.cancelAnimationFrame(rafId)
    }
  },
  unmounted(el: SpotlightElement) {
    el.__spotlightCleanup?.()
    delete el.__spotlightCleanup
  },
}
