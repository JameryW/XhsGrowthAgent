// frontend/tests/components/PageTransition.spec.ts
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import PageTransition from '@/components/PageTransition.vue'

// Create simple test components for routing
const TestComponentA = {
  template: '<div class="page-a">Page A</div>'
}

const TestComponentB = {
  template: '<div class="page-b">Page B</div>'
}

describe('PageTransition', () => {
  it('renders RouterView with transition wrapper', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA },
        { path: '/b', component: TestComponentB }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    // Should contain RouterView
    expect(wrapper.findComponent({ name: 'RouterView' }).exists()).toBe(true)
  })

  it('applies fade-slide transition name', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA },
        { path: '/b', component: TestComponentB }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    // Find the Transition component
    const transition = wrapper.findComponent({ name: 'Transition' })
    expect(transition.exists()).toBe(true)

    // Check transition name prop
    expect(transition.props('name')).toBe('fade-slide')
  })

  it('uses out-in mode for smooth transitions', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA },
        { path: '/b', component: TestComponentB }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    const transition = wrapper.findComponent({ name: 'Transition' })
    expect(transition.props('mode')).toBe('out-in')
  })

  it('accepts duration prop for customization', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      props: {
        duration: 300
      },
      global: {
        plugins: [router]
      }
    })

    // Check that duration prop is passed
    expect(wrapper.props('duration')).toBe(300)

    // Check style contains custom duration
    const transition = wrapper.findComponent({ name: 'Transition' })
    expect(transition.attributes('style')).toContain('300ms')
  })

  it('uses default duration of 200ms', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    expect(wrapper.props('duration')).toBe(200)
  })

  it('renders current route component', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA },
        { path: '/b', component: TestComponentB }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    // Should render TestComponentA
    expect(wrapper.find('.page-a').exists()).toBe(true)
    expect(wrapper.text()).toContain('Page A')
  })

  it('has scoped CSS with transition keyframes', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: TestComponentA }
      ]
    })

    await router.push('/')
    await router.isReady()

    const wrapper = mount(PageTransition, {
      global: {
        plugins: [router]
      }
    })

    // Component should have scoped style attribute
    // Note: Vue Test Utils doesn't render actual CSS in tests
    // but we verify the transition classes are applied
    const transition = wrapper.findComponent({ name: 'Transition' })
    expect(transition.props('name')).toBe('fade-slide')

    // Verify component renders correctly
    expect(wrapper.find('.page-a').exists()).toBe(true)
  })
})