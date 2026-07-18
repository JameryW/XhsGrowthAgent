import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CreatorNoteQualityPanel from '@/components/settings/CreatorNoteQualityPanel.vue'
import {
  getCreatorNote,
  getCreatorNoteQuality,
  getCreatorStats,
} from '@/api/analytics'

vi.mock('@/api/analytics', () => ({
  getCreatorStats: vi.fn(),
  getCreatorNote: vi.fn(),
  getCreatorNoteQuality: vi.fn(),
}))

const mockedGetCreatorStats = vi.mocked(getCreatorStats)
const mockedGetCreatorNote = vi.mocked(getCreatorNote)
const mockedGetCreatorNoteQuality = vi.mocked(getCreatorNoteQuality)

function note(noteId: string, title: string, bodyText: string) {
  return {
    note_id: noteId,
    account_id: 'account-1',
    title,
    body_text: bodyText,
    views: 1000,
    likes: 120,
    comments: 8,
    collects: 50,
    shares: 3,
    published_at: '2026-07-13T00:00:00Z',
    content_type: 'note',
    tags: ['效率'],
    cover_url: '',
    engagement_rate: 0.18,
    synced_at: '2026-07-13T00:00:00Z',
    source: 'creator_statistics',
    view_sources: [{ title: '搜索', value: 20 }],
    audience_profile: [{ title: '女性', value: 0.7 }],
    audience_trend: [{ title: '晚间', value: 12 }],
  }
}

function quality(noteId: string) {
  return {
    account_id: 'account-1',
    note_id: noteId,
    total_notes: 1,
    notes_analyzed: 1,
    scope: 'single_imported_note',
    overall_score: 78,
    grade: 'strong',
    confidence: 'low',
    summary: '单篇质量信号',
    dimensions: [
      { key: 'engagement', score: 80, available: true, evidence: '互动率' },
      { key: 'save_value', score: 70, available: true, evidence: '收藏率' },
      { key: 'title_craft', score: 90, available: true, evidence: '标题' },
      { key: 'consistency', score: 0, available: false, evidence: '需要多篇笔记' },
    ],
    strengths: [],
    weaknesses: [],
    recommendations: [
      {
        priority: 1,
        dimension: 'engagement',
        title: '保持互动引导',
        advice: '继续复用高互动结构',
        evidence: '互动率',
        related_note_ids: [noteId],
      },
    ],
    cold_start: false,
    insufficient_data: false,
  }
}

describe('CreatorNoteQualityPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const first = note('n1', '第一篇效率清单', '第一篇正文')
    const second = note('n2', '第二篇效率清单', '第二篇正文')
    mockedGetCreatorStats.mockResolvedValue({
      account_id: 'account-1',
      account: null,
      notes: [first, second],
      total: 2,
      fetched_at: '2026-07-13T00:00:00Z',
    })
    mockedGetCreatorNote.mockImplementation(async (_accountId, noteId) => ({
      account_id: 'account-1',
      note: noteId === 'n1' ? first : second,
      fetched_at: '2026-07-13T00:00:00Z',
    }))
    mockedGetCreatorNoteQuality.mockImplementation(async (_accountId, noteId) => ({
      account_id: 'account-1',
      note_id: noteId,
      quality: quality(noteId),
      analyzed_at: '2026-07-13T00:00:00Z',
    }))
  })

  it('loads a note detail and quality report, then switches notes', async () => {
    const wrapper = mount(CreatorNoteQualityPanel, {
      props: { accountId: 'account-1', accountName: '测试账号' },
      global: {
        stubs: {
          AppIcon: true,
          NeonButton: { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('第一篇正文')
    expect(wrapper.text()).toContain('78')
    expect(wrapper.text()).toContain('观众画像')

    const secondButton = wrapper.findAll('button').find(button => button.text().includes('第二篇效率清单'))
    expect(secondButton).toBeDefined()
    await secondButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第二篇正文')
    expect(mockedGetCreatorNote).toHaveBeenLastCalledWith('account-1', 'n2')
    expect(mockedGetCreatorNoteQuality).toHaveBeenLastCalledWith('account-1', 'n2', 'zh-CN')
  })

  it('does not silently fall back to the first note for an unmatched drill-down id', async () => {
    const wrapper = mount(CreatorNoteQualityPanel, {
      props: { accountId: 'account-1', noteId: 'workflow-post-without-import' },
      global: {
        stubs: {
          AppIcon: true,
          NeonButton: { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(mockedGetCreatorNote).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('这篇帖子没有可用的历史笔记质量数据')
    expect(wrapper.text()).not.toContain('第一篇正文')
  })

  it('reacts to a changed note id while the drawer remains mounted', async () => {
    const wrapper = mount(CreatorNoteQualityPanel, {
      props: { accountId: 'account-1', noteId: 'n1' },
      global: {
        stubs: {
          AppIcon: true,
          NeonButton: { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('第一篇正文')

    await wrapper.setProps({ noteId: 'n2' })
    await flushPromises()
    expect(wrapper.text()).toContain('第二篇正文')
    expect(mockedGetCreatorNote).toHaveBeenLastCalledWith('account-1', 'n2')
  })
})
