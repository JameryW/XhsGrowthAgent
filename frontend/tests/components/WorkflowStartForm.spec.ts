import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkflowStartForm from '@/components/WorkflowStartForm.vue'
import type { Account } from '@/api/accounts'
import { getActiveAccount, listAccounts } from '@/api/accounts'

vi.mock('@/api/accounts', () => ({
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

vi.mock('@/api/agent', () => ({
  prefetchAgentTuiChunk: vi.fn(),
  prewarmAgentSession: vi.fn().mockResolvedValue({ status: 'warming', mode: 'free' }),
}))

const mockedListAccounts = vi.mocked(listAccounts)
const mockedGetActiveAccount = vi.mocked(getActiveAccount)

function account(id: string, name: string, niche: string, isActive = false): Account {
  return {
    id,
    name,
    niche,
    is_active: isActive,
    created_at: '2026-07-13T00:00:00Z',
  }
}

describe('WorkflowStartForm account niche defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountWithAccounts(accounts: Account[], active: Account | null, initialNiche?: string) {
    mockedListAccounts.mockResolvedValue(accounts)
    mockedGetActiveAccount.mockResolvedValue(active)
    const wrapper = mount(WorkflowStartForm, {
      props: { initialNiche },
    })
    await flushPromises()
    return wrapper
  }

  it('uses the active account bound niche by default', async () => {
    const active = account('beauty', '美妆账号', '美妆', true)
    const wrapper = await mountWithAccounts([active], active)

    expect((wrapper.vm as any).getConfig()).toMatchObject({
      accountId: 'beauty',
      niche: '美妆',
    })
    expect(wrapper.emitted('accountChange')?.at(-1)).toEqual(['beauty'])
    expect(wrapper.text()).toContain('已自动使用账号绑定赛道：美妆')
  })

  it('changes the default niche with the selected account until the user chooses manually', async () => {
    const beauty = account('beauty', '美妆账号', '美妆', true)
    const tech = account('tech', '数码账号', '数码')
    const wrapper = await mountWithAccounts([beauty, tech], beauty)

    await wrapper.find('select').setValue('tech')
    expect((wrapper.vm as any).getConfig().niche).toBe('数码')
    expect(wrapper.emitted('accountChange')?.at(-1)).toEqual(['tech'])

    const foodButton = wrapper.findAll('button').find((button) => button.text().includes('美食'))
    expect(foodButton).toBeDefined()
    await foodButton!.trigger('click')
    await wrapper.find('select').setValue('beauty')

    expect((wrapper.vm as any).getConfig().niche).toBe('美食')
  })

  it('keeps an explicit route niche ahead of the bound account default', async () => {
    const active = account('beauty', '美妆账号', '美妆', true)
    const wrapper = await mountWithAccounts([active], active, '旅行')

    expect((wrapper.vm as any).getConfig().niche).toBe('旅行')
  })

  it('exposes the three creation paths with descriptions and a visible step cue', async () => {
    const wrapper = await mountWithAccounts([], null)

    expect(wrapper.text()).toContain('配置')
    expect(wrapper.text()).toContain('确认')
    expect(wrapper.text()).toContain('创作')
    expect(wrapper.text()).toContain('从热门趋势出发，生成完整内容方案')
    expect(wrapper.text()).toContain('上传商单 Brief，让 AI 按要求完成创作')
    expect(wrapper.text()).toContain('与智能体对话，自由创作、评估并发布')

    const modeButtons = wrapper.findAll('button[role="radio"]')
    expect(modeButtons).toHaveLength(3)
    expect(modeButtons[0].classes()).toContain('min-h-[112px]')
    expect(modeButtons[0].attributes('aria-checked')).toBe('true')
    await modeButtons[2].trigger('click')
    expect((wrapper.vm as any).getConfig().workflowMode).toBe('free')
    expect(modeButtons[2].attributes('aria-checked')).toBe('true')
  })

  it('turns Free Creation into a guided goal hand-off without submitting examples', async () => {
    const wrapper = await mountWithAccounts([], null)
    const freeMode = wrapper.findAll('button[role="radio"]')[2]

    await freeMode.trigger('click')

    expect(wrapper.find('#start-free-goal').exists()).toBe(true)
    expect(wrapper.text()).toContain('自由创作路径')
    expect(wrapper.text()).toContain('描述目标')
    expect(wrapper.text()).toContain('生成内容')
    expect(wrapper.text()).toContain('质量评估')
    expect(wrapper.text()).toContain('审核发布')

    const example = wrapper.findAll('button').find((button) => button.text().includes('写一篇笔记'))
    expect(example).toBeDefined()
    await example!.trigger('click')

    expect((wrapper.find('#start-free-goal').element as HTMLTextAreaElement).value).toContain('京都三天亲子旅行')
    expect((wrapper.vm as any).getConfig()).toMatchObject({
      workflowMode: 'free',
      topic: expect.stringContaining('京都三天亲子旅行'),
    })
    wrapper.unmount()
  })
})
