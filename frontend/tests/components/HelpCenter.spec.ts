import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import HelpCenter from '@/components/HelpCenter.vue'

describe('HelpCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('button rendering', () => {
    it('renders help button', () => {
      const wrapper = mount(HelpCenter)
      expect(wrapper.find('button').exists()).toBe(true)
    })

    it('has correct aria attributes on button', () => {
      const wrapper = mount(HelpCenter)
      const btn = wrapper.find('button')
      expect(btn.attributes('aria-label')).toBe('帮助中心')
      expect(btn.attributes('aria-haspopup')).toBe('true')
    })

    it('has aria-expanded attribute', () => {
      const wrapper = mount(HelpCenter)
      const btn = wrapper.find('button')
      expect(btn.attributes('aria-expanded')).toBe('false')
    })

    it('updates aria-expanded when dropdown opens', async () => {
      const wrapper = mount(HelpCenter)
      const btn = wrapper.find('button')
      await btn.trigger('click')
      expect(btn.attributes('aria-expanded')).toBe('true')
    })
  })

  describe('dropdown display', () => {
    it('hides dropdown initially', () => {
      const wrapper = mount(HelpCenter)
      expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    })

    it('shows dropdown when button clicked', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(true)
    })

    it('hides dropdown when button clicked again', async () => {
      const wrapper = mount(HelpCenter)
      const btn = wrapper.find('button')

      // Open
      await btn.trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(true)

      // Close
      await btn.trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    })

    it('has correct menu items', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const items = wrapper.findAll('[role="menuitem"]')
      expect(items.length).toBe(3)
      expect(wrapper.text()).toContain('常见问题')
      expect(wrapper.text()).toContain('快捷键')
      expect(wrapper.text()).toContain('反馈建议')
    })

    it('has divider between shortcuts and feedback', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      expect(wrapper.find('.border-t').exists()).toBe(true)
    })
  })

  describe('link functionality', () => {
    it('emits open-faq event when FAQ clicked', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const items = wrapper.findAll('[role="menuitem"]')
      const faqBtn = items.find(item => item.text().includes('常见问题'))
      await faqBtn?.trigger('click')

      expect(wrapper.emitted('open-faq')).toBeTruthy()
    })

    it('emits open-shortcuts event when Shortcuts clicked', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const items = wrapper.findAll('[role="menuitem"]')
      const shortcutsBtn = items.find(item => item.text().includes('快捷键'))
      await shortcutsBtn?.trigger('click')

      expect(wrapper.emitted('open-shortcuts')).toBeTruthy()
    })

    it('emits send-feedback event when Feedback clicked', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const items = wrapper.findAll('[role="menuitem"]')
      const feedbackBtn = items.find(item => item.text().includes('反馈建议'))
      await feedbackBtn?.trigger('click')

      expect(wrapper.emitted('send-feedback')).toBeTruthy()
    })

    it('closes dropdown after clicking item', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(true)

      const items = wrapper.findAll('[role="menuitem"]')
      await items[0].trigger('click')

      expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    })
  })

  describe('keyboard interaction', () => {
    it('closes dropdown on Escape key', async () => {
      const wrapper = mount(HelpCenter, { attachTo: document.body })
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(true)

      // Trigger Escape on document
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="menu"]').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  describe('outside click', () => {
    it('closes dropdown on outside click', async () => {
      const wrapper = mount(HelpCenter, { attachTo: document.body })
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('[role="menu"]').exists()).toBe(true)

      // Simulate click outside
      document.body.click()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="menu"]').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  describe('accessibility', () => {
    it('has proper ARIA attributes on menu', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const menu = wrapper.find('[role="menu"]')
      expect(menu.attributes('aria-label')).toBe('帮助菜单')
    })

    it('has role="menuitem" on all items', async () => {
      const wrapper = mount(HelpCenter)
      await wrapper.find('button').trigger('click')

      const items = wrapper.findAll('[role="menuitem"]')
      expect(items.length).toBe(3)
    })
  })

  describe('custom props', () => {
    it('accepts custom faqUrl', () => {
      const wrapper = mount(HelpCenter, {
        props: { faqUrl: '/custom-faq' }
      })
      expect(wrapper.props('faqUrl')).toBe('/custom-faq')
    })

    it('accepts custom shortcutsUrl', () => {
      const wrapper = mount(HelpCenter, {
        props: { shortcutsUrl: '/custom-shortcuts' }
      })
      expect(wrapper.props('shortcutsUrl')).toBe('/custom-shortcuts')
    })

    it('accepts custom feedbackEmail', () => {
      const wrapper = mount(HelpCenter, {
        props: { feedbackEmail: 'test@test.com' }
      })
      expect(wrapper.props('feedbackEmail')).toBe('test@test.com')
    })
  })
})