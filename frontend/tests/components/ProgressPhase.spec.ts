import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProgressPhase from '@/components/ProgressPhase.vue'

describe('ProgressPhase', () => {
  it('renders progress bar with correct width', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 50 }
    })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('width: 50%')
  })

  it('applies correct color for scouting phase', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 10, currentPhase: 'scouting' }
    })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('#f43f5e')
  })

  it('displays phase name label', () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 20, currentPhase: 'planning' }
    })
    expect(wrapper.text()).toContain('内容策划')
  })

  it('updates progress percent reactively', async () => {
    const wrapper = mount(ProgressPhase, {
      props: { percent: 10 }
    })
    await wrapper.setProps({ percent: 60 })
    const progressBar = wrapper.find('.progress-bar-fill')
    expect(progressBar.attributes('style')).toContain('width: 60%')
  })
})
