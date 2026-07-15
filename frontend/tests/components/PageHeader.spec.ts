import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PageHeader from '@/components/PageHeader.vue'

describe('PageHeader', () => {
  it('renders the page purpose, description and named slots', () => {
    const wrapper = mount(PageHeader, {
      props: {
        title: '数据分析',
        description: '查看账号表现',
        eyebrow: '工作区',
        icon: 'BarChart3',
        tone: 'cyan',
      },
      slots: {
        meta: '<span>当前账号</span>',
        actions: '<button class="min-h-11">刷新</button>',
      },
    })

    expect(wrapper.find('h1').text()).toBe('数据分析')
    expect(wrapper.text()).toContain('查看账号表现')
    expect(wrapper.text()).toContain('当前账号')
    expect(wrapper.find('button').classes()).toContain('min-h-11')
    expect(wrapper.find('header').attributes('aria-labelledby')).toBe('page-title')
  })
})
