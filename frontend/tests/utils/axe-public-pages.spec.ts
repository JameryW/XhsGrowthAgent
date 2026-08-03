// INF-09: axe-core accessibility gate for public-page key states.
// Asserts 0 critical violations on the components that compose Showcase /
// WorkflowReplay loading + error surfaces. happy-dom skips contrast rules
// (no layout engine) — see tests/utils/axe.ts.
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ErrorState from '@/components/ErrorState.vue'
import TooltipHelper from '@/components/TooltipHelper.vue'
import { SkeletonLoader } from '@/components/skeletons'
import { assertNoCriticalAxeViolations } from './axe'

describe('public-page a11y (axe, 0 critical)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })
  it('ErrorState — api variant', async () => {
    const wrapper = mount(ErrorState, {
      props: { variant: 'api', title: 'Error', message: 'Something broke', retryLabel: 'Retry' },
      attachTo: document.body,
    })
    await assertNoCriticalAxeViolations(document.body)
    wrapper.unmount()
  })

  it('ErrorState — timeout variant', async () => {
    const wrapper = mount(ErrorState, {
      props: { variant: 'timeout', title: 'Timeout', message: 'slow', retryLabel: 'Retry' },
      attachTo: document.body,
    })
    await assertNoCriticalAxeViolations(document.body)
    wrapper.unmount()
  })

  it('ErrorState — unknown variant', async () => {
    const wrapper = mount(ErrorState, {
      props: { variant: 'unknown', title: 'Unknown', message: '?' },
      attachTo: document.body,
    })
    await assertNoCriticalAxeViolations(document.body)
    wrapper.unmount()
  })

  it('SkeletonLoader renders without critical a11y issues', async () => {
    const wrapper = mount(SkeletonLoader, { props: { type: 'card' }, attachTo: document.body })
    await assertNoCriticalAxeViolations(document.body)
    wrapper.unmount()
  })

  it('TooltipHelper — trigger + tooltip content accessible', async () => {
    const wrapper = mount(
      TooltipHelper,
      {
        props: { content: 'Helpful explanation', position: 'top' },
        slots: { default: '<button type="button">?</button>' },
        attachTo: document.body,
      },
    )
    await assertNoCriticalAxeViolations(document.body)
    wrapper.unmount()
  })
})
