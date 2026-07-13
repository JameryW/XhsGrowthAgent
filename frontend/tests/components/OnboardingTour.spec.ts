import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import OnboardingTour from '@/components/OnboardingTour.vue'

// Mock ResizeObserver
vi.stubGlobal('ResizeObserver', vi.fn(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})))

describe('OnboardingTour', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('overlay rendering', () => {
    it('renders overlay when isActive=true', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
      expect(wrapper.find('[aria-modal="true"]').exists()).toBe(true)
    })

    it('hides overlay when isActive=false', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: false, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    })

    it('has correct z-index for overlay', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const overlay = wrapper.find('.fixed.inset-0')
      expect(overlay.classes()).toContain('z-50')
    })

    it('renders backdrop with blur effect', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const backdrop = wrapper.find('.bg-slate-900\\/60')
      expect(backdrop.exists()).toBe(true)
      expect(backdrop.classes()).toContain('backdrop-blur-sm')
    })
  })

  describe('step display', () => {
    it('shows step 1 content when currentStep=1', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('了解工作流')
    })

    it('shows step 2 content when currentStep=2', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 2 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('开始创作')
    })

    it('shows step 3 content when currentStep=3', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 3 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('审核与发布')
    })

    it('shows step indicator dots', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const dots = wrapper.find('[role="group"]')
      expect(dots.exists()).toBe(true)
      // Should have 3 dots
      expect(wrapper.findAll('.rounded-full').length).toBe(3)
    })

    it('marks current step dot as active', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 2 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const dots = wrapper.findAll('.rounded-full')
      // Second dot should have cyan color
      expect(dots[1].classes()).toContain('bg-neon-cyan')
      expect(dots[1].classes()).toContain('scale-125')
    })

    it('shows completed steps with partial color', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 3 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const dots = wrapper.findAll('.rounded-full')
      // First two dots should show completed state (with opacity 50)
      // Check for the color in the classes (escaped slash in test)
      const firstDotClasses = dots[0].classes()
      const secondDotClasses = dots[1].classes()
      // Both should have neon-cyan color (either with /50 or regular)
      expect(firstDotClasses.some(c => c.includes('neon-cyan'))).toBe(true)
      expect(secondDotClasses.some(c => c.includes('neon-cyan'))).toBe(true)
    })

    it('shows future steps with muted color', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const dots = wrapper.findAll('.rounded-full')
      // Future dots should be slate
      expect(dots[1].classes()).toContain('bg-slate-300')
      expect(dots[2].classes()).toContain('bg-slate-300')
    })
  })

  describe('button functionality', () => {
    it('shows Skip button on all steps', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('跳过')
    })

    it('shows Next button on non-last steps', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('下一步')
    })

    it('shows Complete button on last step', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 3 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('完成')
      expect(wrapper.text()).not.toContain('下一步')
    })

    it('emits skip event when Skip button clicked', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const buttons = wrapper.findAll('button')
      const skipBtn = buttons.find(b => b.text() === '跳过引导')
      await skipBtn?.trigger('click')
      expect(wrapper.emitted('skip')).toBeTruthy()
    })

    it('emits next event when Next button clicked', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const buttons = wrapper.findAll('button')
      const nextBtn = buttons.find(b => b.text() === '下一步')
      await nextBtn?.trigger('click')
      expect(wrapper.emitted('next')).toBeTruthy()
    })

    it('emits complete event when Complete button clicked', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 3 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const buttons = wrapper.findAll('button')
      const completeBtn = buttons.find(b => b.text() === '完成引导')
      await completeBtn?.trigger('click')
      expect(wrapper.emitted('complete')).toBeTruthy()
    })
  })

  describe('accessibility', () => {
    it('has proper ARIA attributes', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
      expect(wrapper.find('[aria-modal="true"]').exists()).toBe(true)
      expect(wrapper.find('[aria-labelledby="tour-title"]').exists()).toBe(true)
      expect(wrapper.find('[aria-describedby="tour-desc"]').exists()).toBe(true)
    })

    it('has accessible step indicator', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const indicator = wrapper.find('[role="group"]')
      expect(indicator.attributes('aria-label')).toBe('步骤指示器')
    })

    it('has aria-label on buttons', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const buttons = wrapper.findAll('button')
      for (const btn of buttons) {
        expect(btn.attributes('aria-label')).toBeDefined()
      }
    })
  })
})
