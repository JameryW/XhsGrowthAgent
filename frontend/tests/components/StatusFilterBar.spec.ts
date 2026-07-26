import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusFilterBar from '@/components/StatusFilterBar.vue'

describe('StatusFilterBar', () => {
  it('emits selected filter value', async () => {
    const wrapper = mount(StatusFilterBar, {
      props: {
        label: 'Status',
        modelValue: 'all',
        options: [
          { value: 'all', label: 'All', count: 3 },
          { value: 'running', label: 'Running', count: 1 },
        ],
      },
    })
    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(2)
    await buttons[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['running'])
  })
})
