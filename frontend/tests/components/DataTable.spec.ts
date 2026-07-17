import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '@/components/DataTable.vue'

const rows = [
  { title: 'a', views_display: '999', views: 999, engagement_rate_display: '9.0%', engagement_rate: 9.0 },
  { title: 'b', views_display: '1,234', views: 1234, engagement_rate_display: '10.0%', engagement_rate: 10.0 },
  { title: 'c', views_display: '500', views: 500, engagement_rate_display: '1.5%', engagement_rate: 1.5 },
]

const columns = [
  { key: 'title', label: 'Title' },
  { key: 'views_display', label: 'Views', align: 'center' as const, sortable: true, sortKey: 'views' },
  { key: 'engagement_rate_display', label: 'Rate', align: 'center' as const, sortable: true, sortKey: 'engagement_rate' },
]

function headerButton(wrapper: ReturnType<typeof mount>, colKey: string) {
  const headers = wrapper.findAll('[role="columnheader"]')
  const idx = columns.findIndex(c => c.key === colKey)
  return headers[idx].find('button')
}

function rowTitles(wrapper: ReturnType<typeof mount>): string[] {
  // data rows are role="row"; header/footer are role="rowgroup".
  return wrapper.findAll('[role="row"]').map(r => r.text())
}

describe('DataTable sorting (AN-03)', () => {
  it('sorts formatted views by the raw numeric value, not the string', async () => {
    const wrapper = mount(DataTable, { props: { columns, data: rows } })
    // default order: desc by first sortable click
    await headerButton(wrapper, 'views_display').trigger('click')
    const titles = rowTitles(wrapper)
    // 1234 > 999 > 500 → b, a, c
    expect(titles[0]).toContain('b')
    expect(titles[2]).toContain('c')
  })

  it('sorts formatted engagement rate by the raw numeric value', async () => {
    const wrapper = mount(DataTable, { props: { columns, data: rows } })
    await headerButton(wrapper, 'engagement_rate_display').trigger('click')
    const titles = rowTitles(wrapper)
    // 10.0 > 9.0 > 1.5 → b, a, c
    expect(titles[0]).toContain('b')
    expect(titles[2]).toContain('c')
  })

  it('toggles to ascending on a second click', async () => {
    const wrapper = mount(DataTable, { props: { columns, data: rows } })
    const btn = headerButton(wrapper, 'views_display')
    await btn.trigger('click') // desc
    await btn.trigger('click') // asc
    const titles = rowTitles(wrapper)
    // asc: 500 < 999 < 1234 → c, a, b
    expect(titles[0]).toContain('c')
    expect(titles[2]).toContain('b')
  })
})
