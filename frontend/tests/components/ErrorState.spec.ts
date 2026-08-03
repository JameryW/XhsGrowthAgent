// frontend/tests/components/ErrorState.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ErrorState from '@/components/ErrorState.vue'

describe('ErrorState (presentational mode, INF-01)', () => {
  const baseProps = {
    variant: 'api' as const,
    title: '加载失败',
    message: '网络开小差了',
  }

  it('renders title and message from props without store data', () => {
    const wrapper = mount(ErrorState, { props: baseProps })
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).toContain('网络开小差了')
  })

  it('emits retry when the retry button is clicked', async () => {
    const wrapper = mount(ErrorState, { props: baseProps })
    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('hides the dismiss button when hide-dismiss is set', () => {
    const wrapper = mount(ErrorState, { props: { ...baseProps, hideDismiss: true } })
    expect(wrapper.findAll('button')).toHaveLength(1)
    expect(wrapper.emitted('dismiss')).toBeUndefined()
  })

  it('shows dismiss button and emits dismiss by default', async () => {
    const wrapper = mount(ErrorState, { props: baseProps })
    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(2)
    await buttons[1].trigger('click')
    expect(wrapper.emitted('dismiss')).toHaveLength(1)
  })

  it('omits the retry button for retry_success variant', () => {
    const wrapper = mount(ErrorState, {
      props: { variant: 'retry_success' as const, title: '成功', message: 'ok' },
    })
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})
