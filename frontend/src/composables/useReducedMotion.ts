// INF-05: reactive prefers-reduced-motion. Components read this to gate JS-driven
// animation (AnimatedCounter, confetti, count-ups) — CSS @media handles the
// declarative ones. SSR-safe: defaults to false when matchMedia is absent.
import { ref } from 'vue'

// Shared singleton so the listener is installed once app-wide.
export const prefersReducedMotion = ref(false)

if (typeof window !== 'undefined' && window.matchMedia) {
  const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
  prefersReducedMotion.value = mql.matches
  const handler = (e: MediaQueryListEvent) => {
    prefersReducedMotion.value = e.matches
  }
  if (mql.addEventListener) mql.addEventListener('change', handler)
  else if ((mql as any).addListener) (mql as any).addListener(handler)
}

export function useReducedMotion() {
  return { prefersReduced }
}

const prefersReduced = prefersReducedMotion
