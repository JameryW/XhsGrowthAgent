// INF-06: lightweight focus trap for self-built modals. Constrains Tab/Shift-Tab
// to focusable elements inside a container and restores focus to the trigger on
// teardown. Intentionally minimal — not a full a11y library; the three modal
// sites (ConfirmModal/CelebrationModal/Analytics drawer) share this instead of
// each reimplementing.
import { nextTick, onBeforeUnmount, ref } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useFocusTrap() {
  const container = ref<HTMLElement | null>(null)
  let previouslyFocused: HTMLElement | null = null

  function trap(event: KeyboardEvent) {
    if (event.key !== 'Tab' || !container.value) return
    const els = Array.from(container.value.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (!els.length) return
    const first = els[0]
    const last = els[els.length - 1]
    const active = document.activeElement as HTMLElement | null
    if (event.shiftKey && active === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  async function activate(el: HTMLElement | null) {
    container.value = el
    if (!el) return
    previouslyFocused = document.activeElement as HTMLElement | null
    el.addEventListener('keydown', trap)
    await nextTick()
    const first = el.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
  }

  function deactivate() {
    container.value?.removeEventListener('keydown', trap)
    container.value = null
    // Restore focus to whatever opened the modal.
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }

  onBeforeUnmount(deactivate)
  return { activate, deactivate }
}
