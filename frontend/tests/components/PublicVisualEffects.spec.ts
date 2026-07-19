import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import AuroraBackground from '@/components/showcase/AuroraBackground.vue'
import type { Directive } from 'vue'

function stubMatchMedia({ reduced = false, coarse = false } = {}) {
  vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches: query.includes('prefers-reduced-motion') ? reduced : query.includes('pointer: coarse') ? coarse : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }) as unknown as MediaQueryList)
}

async function freshRevealDirective(): Promise<Directive<HTMLElement, number | string | undefined>> {
  vi.resetModules()
  const mod = await import('@/directives/reveal')
  return mod.vReveal
}

async function freshSpotlightDirective(): Promise<Directive<HTMLElement>> {
  vi.resetModules()
  const mod = await import('@/directives/spotlight')
  return mod.vSpotlight
}

describe('AuroraBackground', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders a decorative aria-hidden layer', () => {
    stubMatchMedia({ reduced: true })
    const wrapper = mount(AuroraBackground)
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.classes()).toContain('aurora-rose')
    wrapper.unmount()
  })

  it('updates the spotlight position on pointermove for fine pointers with full motion', async () => {
    stubMatchMedia({ reduced: false, coarse: false })
    const wrapper = mount(AuroraBackground, { props: { variant: 'teal' } })
    expect(wrapper.classes()).toContain('aurora-teal')
    wrapper.element.dispatchEvent(new MouseEvent('pointermove', { clientX: 120, clientY: 60 }))
    await new Promise(resolve => requestAnimationFrame(resolve))
    const el = wrapper.element as HTMLElement
    expect(el.style.getPropertyValue('--mx')).toBe('120px')
    expect(el.style.getPropertyValue('--my')).toBe('60px')
    wrapper.unmount()
  })

  it('ignores the pointer under reduced motion or coarse pointers', async () => {
    stubMatchMedia({ reduced: true, coarse: true })
    const wrapper = mount(AuroraBackground)
    wrapper.element.dispatchEvent(new MouseEvent('pointermove', { clientX: 120, clientY: 60 }))
    await new Promise(resolve => requestAnimationFrame(resolve))
    const el = wrapper.element as HTMLElement
    expect(el.style.getPropertyValue('--mx')).toBe('')
    expect(el.style.getPropertyValue('--my')).toBe('')
    wrapper.unmount()
  })
})

describe('v-spotlight directive', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('activates on pointer enter and tracks the cursor position', async () => {
    stubMatchMedia({ reduced: false, coarse: false })
    const vSpotlight = await freshSpotlightDirective()
    const Comp = defineComponent({
      directives: { spotlight: vSpotlight },
      template: '<div v-spotlight data-test="target" />',
    })
    const wrapper = mount(Comp)
    const el = wrapper.find('[data-test="target"]').element as HTMLElement
    expect(el.classList.contains('spotlight-card')).toBe(true)

    el.dispatchEvent(new MouseEvent('pointerenter'))
    expect(el.classList.contains('spotlight-active')).toBe(true)

    el.dispatchEvent(new MouseEvent('pointermove', { clientX: 30, clientY: 20 }))
    await new Promise(resolve => requestAnimationFrame(resolve))
    expect(el.style.getPropertyValue('--sx')).toBe('30px')
    expect(el.style.getPropertyValue('--sy')).toBe('20px')

    el.dispatchEvent(new MouseEvent('pointerleave'))
    expect(el.classList.contains('spotlight-active')).toBe(false)
    wrapper.unmount()
  })

  it('stays inert under reduced motion or coarse pointers', async () => {
    stubMatchMedia({ reduced: true, coarse: true })
    const vSpotlight = await freshSpotlightDirective()
    const Comp = defineComponent({
      directives: { spotlight: vSpotlight },
      template: '<div v-spotlight data-test="target" />',
    })
    const wrapper = mount(Comp)
    const el = wrapper.find('[data-test="target"]').element as HTMLElement
    expect(el.classList.contains('spotlight-card')).toBe(false)
    el.dispatchEvent(new MouseEvent('pointerenter'))
    expect(el.classList.contains('spotlight-active')).toBe(false)
    wrapper.unmount()
  })
})

describe('v-reveal directive', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('falls back to immediately visible when IntersectionObserver is unavailable', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const vReveal = await freshRevealDirective()
    const Comp = defineComponent({
      directives: { reveal: vReveal },
      template: '<div v-reveal data-test="target" />',
    })
    const wrapper = mount(Comp)
    const el = wrapper.find('[data-test="target"]').element
    expect(el.classList.contains('reveal-visible')).toBe(true)
    expect(el.classList.contains('reveal-base')).toBe(false)
    wrapper.unmount()
  })

  it('hides first, then reveals with the stagger delay on intersection', async () => {
    let observerCallback: IntersectionObserverCallback | null = null
    const observe = vi.fn()
    const unobserve = vi.fn()
    class MockIntersectionObserver implements IntersectionObserver {
      readonly root = null
      readonly rootMargin = '0px'
      readonly thresholds = [0]
      constructor(callback: IntersectionObserverCallback) {
        observerCallback = callback
      }
      observe = observe
      unobserve = unobserve
      disconnect = vi.fn()
      takeRecords = () => []
    }
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
    const vReveal = await freshRevealDirective()
    const Comp = defineComponent({
      directives: { reveal: vReveal },
      template: '<div v-reveal="120" data-test="target" />',
    })
    const wrapper = mount(Comp)
    const el = wrapper.find('[data-test="target"]').element as HTMLElement
    expect(el.classList.contains('reveal-base')).toBe(true)
    expect(el.style.getPropertyValue('--reveal-delay')).toBe('120ms')
    expect(observe).toHaveBeenCalledWith(el)

    expect(observerCallback).not.toBeNull()
    observerCallback!([{ isIntersecting: true, target: el } as IntersectionObserverEntry], {} as IntersectionObserver)
    expect(el.classList.contains('reveal-visible')).toBe(true)
    expect(unobserve).toHaveBeenCalledWith(el)
    wrapper.unmount()
  })
})
