import type { Directive } from 'vue'

let observer: IntersectionObserver | null = null

function getObserver(): IntersectionObserver | null {
  if (typeof IntersectionObserver === 'undefined') return null
  if (!observer) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('reveal-visible')
          observer?.unobserve(entry.target)
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -6% 0px' },
    )
  }
  return observer
}

/**
 * v-reveal — fades/slides an element in the first time it scrolls into view.
 * Binding value: optional stagger delay in ms (`v-reveal="120"`).
 * Styles live in `src/styles/public-pages.css` (.reveal-base/.reveal-visible).
 * Falls back to immediately visible when IntersectionObserver is unavailable.
 */
export const vReveal: Directive<HTMLElement, number | string | undefined> = {
  mounted(el, binding) {
    const delay = Number(binding.value)
    if (Number.isFinite(delay) && delay > 0) {
      el.style.setProperty('--reveal-delay', `${Math.round(delay)}ms`)
    }
    const activeObserver = getObserver()
    if (!activeObserver) {
      el.classList.add('reveal-visible')
      return
    }
    el.classList.add('reveal-base')
    activeObserver.observe(el)
  },
  unmounted(el) {
    observer?.unobserve(el)
  },
}
