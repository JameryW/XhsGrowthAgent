import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CelebrationModal from '@/components/CelebrationModal.vue'
import { prefersReducedMotion } from '@/composables/useReducedMotion'
import i18n from '@/locales'

const global = {
  plugins: [i18n],
  stubs: {
    AppIcon: { template: '<span />' },
    Teleport: { template: '<div><slot /></div>' },
    Transition: { template: '<div><slot /></div>' },
  },
}

describe('CelebrationModal', () => {
  beforeEach(() => {
    prefersReducedMotion.value = false
  })

  afterEach(() => {
    prefersReducedMotion.value = false
  })

  it('renders a real post link and emits both completion CTAs', async () => {
    const wrapper = mount(CelebrationModal, {
      global,
      props: {
        show: true,
        copyCount: 2,
        imageCount: 3,
        postUrl: 'https://www.xiaohongshu.com/explore/example',
      },
    })

    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('3')

    const postLink = wrapper.find('[data-testid="celebration-view-post"]')
    expect(postLink.attributes('href')).toBe('https://www.xiaohongshu.com/explore/example')
    expect(postLink.attributes('target')).toBe('_blank')
    postLink.element.addEventListener('click', event => event.preventDefault(), { once: true })
    await postLink.trigger('click')
    await wrapper.find('[data-testid="celebration-replay"]').trigger('click')

    expect(wrapper.emitted('view-post')).toHaveLength(1)
    expect(wrapper.emitted('replay')).toHaveLength(1)
  })

  it('degrades safely when there is no post URL', () => {
    const wrapper = mount(CelebrationModal, {
      global,
      props: { show: true, postUrl: ' ' },
    })

    expect(wrapper.find('[data-testid="celebration-view-post"]').exists()).toBe(false)
    expect(wrapper.text()).toContain(i18n.global.t('celebration.postUnavailable'))
    expect(wrapper.find('[data-testid="celebration-replay"]').exists()).toBe(true)
  })

  it('does not render confetti and removes it when reduced motion is enabled', async () => {
    prefersReducedMotion.value = true
    const wrapper = mount(CelebrationModal, {
      global,
      props: { show: true },
    })

    expect(wrapper.find('.motion-reduced').exists()).toBe(true)
    expect(wrapper.find('.animate-confetti').exists()).toBe(false)

    prefersReducedMotion.value = false
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.animate-confetti').exists()).toBe(true)

    prefersReducedMotion.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.animate-confetti').exists()).toBe(false)
  })

  it('hides replay when the parent marks the modal as non-replayable', () => {
    const wrapper = mount(CelebrationModal, {
      global,
      props: { show: true, canReplay: false },
    })

    expect(wrapper.find('[data-testid="celebration-replay"]').exists()).toBe(false)
  })
})
