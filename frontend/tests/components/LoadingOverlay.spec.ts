import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LoadingOverlay from '@/components/LoadingOverlay.vue'

describe('LoadingOverlay', () => {
  it('renders overlay when visible=true', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    expect(wrapper.find('.loading-overlay').exists()).toBe(true)
    expect(wrapper.find('.loading-overlay').isVisible()).toBe(true)
  })

  it('hides overlay when visible=false', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: false }
    })
    expect(wrapper.find('.loading-overlay').exists()).toBe(false)
  })

  it('displays default loading message', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    expect(wrapper.text()).toContain('正在处理...')
  })

  it('displays custom loading message', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, message: '正在发布内容...' }
    })
    expect(wrapper.text()).toContain('正在发布内容...')
  })

  it('shows cancel button when canCancel=true (default)', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    expect(wrapper.find('button').exists()).toBe(true)
    expect(wrapper.text()).toContain('取消操作')
  })

  it('hides cancel button when canCancel=false', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true, canCancel: false }
    })
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('emits cancel event when cancel button clicked', async () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    const cancelButton = wrapper.find('button')
    await cancelButton.trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('cancel').length).toBe(1)
  })

  it('shows rotating spinner with rotate-animation class', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    const spinner = wrapper.find('.rotate-animation')
    expect(spinner.exists()).toBe(true)
    // Check that spinner has appropriate size classes
    expect(spinner.classes()).toContain('w-16')
    expect(spinner.classes()).toContain('h-16')
  })

  it('has proper overlay structure with backdrop and content', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    // Check backdrop exists
    expect(wrapper.find('.bg-slate-900\\/40').exists()).toBe(true)
    // Check content container exists
    expect(wrapper.find('.bg-white').exists()).toBe(true)
    // Check modal dialog attributes
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.find('[aria-modal="true"]').exists()).toBe(true)
  })

  it('has proper z-index for full-screen overlay', () => {
    const wrapper = mount(LoadingOverlay, {
      props: { isVisible: true }
    })
    const overlay = wrapper.find('.loading-overlay')
    expect(overlay.classes()).toContain('fixed')
    expect(overlay.classes()).toContain('inset-0')
    expect(overlay.classes()).toContain('z-50')
  })
})