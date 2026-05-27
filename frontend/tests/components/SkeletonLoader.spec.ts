import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SkeletonLoader from '@/components/SkeletonLoader.vue'

describe('SkeletonLoader', () => {
  it('renders text skeleton with multiple lines', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'text', lines: 3 }
    })
    expect(wrapper.findAll('.skeleton-text-line')).toHaveLength(3)
  })

  it('renders card skeleton with correct width', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'card', width: 300 }
    })
    const card = wrapper.find('.skeleton-card')
    expect(card.attributes('style')).toContain('width: 300px')
  })

  it('renders avatar skeleton with correct size', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'avatar', size: 48 }
    })
    const avatar = wrapper.find('.skeleton-avatar')
    expect(avatar.attributes('style')).toContain('width: 48px')
    expect(avatar.attributes('style')).toContain('height: 48px')
  })

  it('applies shimmer animation class', () => {
    const wrapper = mount(SkeletonLoader, {
      props: { type: 'text', lines: 1 }
    })
    expect(wrapper.find('.shimmer-animation')).toBeDefined()
  })
})