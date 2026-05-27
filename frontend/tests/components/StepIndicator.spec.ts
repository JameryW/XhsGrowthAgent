import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StepIndicator from '@/components/StepIndicator.vue'

describe('StepIndicator', () => {
  const mockSteps = [
    { name: 'Step 1', status: 'completed' as const },
    { name: 'Step 2', status: 'active' as const },
    { name: 'Step 3', status: 'pending' as const }
  ]

  it('renders all steps', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const stepItems = wrapper.findAll('.step-item')
    expect(stepItems.length).toBe(3)
  })

  it('shows check icon for completed status', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const firstStep = wrapper.findAll('.step-item')[0]
    // Check for Check icon (from AppIcon component)
    expect(firstStep.find('.bg-teal-500').exists()).toBe(true)
  })

  it('shows pulse icon for active status', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const secondStep = wrapper.findAll('.step-item')[1]
    // Check for active styling (rose-500 background + pulse)
    expect(secondStep.find('.bg-rose-500').exists()).toBe(true)
    expect(secondStep.find('.pulse-animation').exists()).toBe(true)
  })

  it('shows number for pending status', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const thirdStep = wrapper.findAll('.step-item')[2]
    // Check for number display (pending steps show step number)
    expect(thirdStep.text()).toContain('3')
    expect(thirdStep.find('.bg-slate-200').exists()).toBe(true)
  })

  it('displays step names', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    expect(wrapper.text()).toContain('Step 1')
    expect(wrapper.text()).toContain('Step 2')
    expect(wrapper.text()).toContain('Step 3')
  })

  it('defaults to vertical layout', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    expect(wrapper.find('.step-indicator-wrapper').classes()).toContain('vertical')
  })

  it('supports horizontal layout', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps, layout: 'horizontal' }
    })
    expect(wrapper.find('.step-indicator-wrapper').classes()).toContain('horizontal')
  })

  it('shows connector lines in vertical layout between steps', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps, layout: 'vertical' }
    })
    // Should have connector lines between steps (n-1 connectors for n steps)
    const connectors = wrapper.findAll('.w-0\\.5')
    expect(connectors.length).toBe(2) // 3 steps = 2 connectors
  })

  it('does not show connector line after last step', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps, layout: 'vertical' }
    })
    const lastStep = wrapper.findAll('.step-item')[2]
    // Last step should not have a connector line within it
    const stepItems = wrapper.findAll('.step-item')
    const lastStepHtml = lastStep.html()
    // The connector line logic: only shows if i < steps.length - 1
    // So last step should not have connector
    expect(lastStepHtml).not.toContain('h-6') // connector has h-6 class
  })

  it('applies active text styling to active step', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const secondStep = wrapper.findAll('.step-item')[1]
    const stepLabel = secondStep.find('.text-sm')
    expect(stepLabel.classes()).toContain('text-slate-800')
  })

  it('applies muted text styling to non-active steps', () => {
    const wrapper = mount(StepIndicator, {
      props: { steps: mockSteps }
    })
    const firstStep = wrapper.findAll('.step-item')[0]
    const thirdStep = wrapper.findAll('.step-item')[2]
    expect(firstStep.find('.text-sm').classes()).toContain('text-slate-500')
    expect(thirdStep.find('.text-sm').classes()).toContain('text-slate-500')
  })

  it('renders single step correctly', () => {
    const singleStep = [{ name: 'Only Step', status: 'active' as const }]
    const wrapper = mount(StepIndicator, {
      props: { steps: singleStep }
    })
    expect(wrapper.findAll('.step-item').length).toBe(1)
    // No connector lines for single step
    expect(wrapper.findAll('.w-0\\.5').length).toBe(0)
  })
})