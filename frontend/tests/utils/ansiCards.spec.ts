// frontend/tests/utils/ansiCards.spec.ts
import { describe, it, expect } from 'vitest'
import {
  getStringWidth,
  padEndDisplay,
  truncateDisplay,
  wrapDisplay,
  cardWidth,
  boxTitleLine,
  writeBoxTitle,
  boxLine,
  boxBottom,
  hr,
  kvLine,
  badge,
  writeEmptyState,
  writeError,
} from '@/utils/ansiCards'
import { ANSI } from '@/utils/markdownToAnsi'

/** Strip ANSI SGR sequences so display width can be measured. */
const strip = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, '')

describe('ansiCards', () => {
  describe('getStringWidth', () => {
    it('counts ASCII chars as width 1', () => {
      expect(getStringWidth('abc /start')).toBe(10)
    })

    it('counts CJK chars as width 2', () => {
      expect(getStringWidth('草稿')).toBe(4)
      expect(getStringWidth('a草稿b')).toBe(6)
    })
  })

  describe('padEndDisplay / truncateDisplay', () => {
    it('pads to display width accounting for CJK', () => {
      expect(padEndDisplay('草稿', 6)).toBe('草稿  ')
      expect(padEndDisplay('abcdef', 4)).toBe('abcdef')
    })

    it('truncates by display width with ellipsis', () => {
      expect(truncateDisplay('hello world', 8)).toBe('hello w…')
      expect(truncateDisplay('短', 8)).toBe('短')
      expect(getStringWidth(truncateDisplay('小红书内容增长工作台', 9))).toBeLessThanOrEqual(9)
    })
  })

  describe('cardWidth', () => {
    it('clamps to the 36..64 adaptive range', () => {
      expect(cardWidth(30)).toBe(36)
      expect(cardWidth(50)).toBe(46)
      expect(cardWidth(200)).toBe(64)
    })
  })

  describe('boxTitleLine', () => {
    it('renders an accent border with the title at exact display width', () => {
      const line = boxTitleLine('Drafts', { width: 40 })
      expect(getStringWidth(strip(line))).toBe(40)
      expect(strip(line)).toContain('Drafts')
      expect(strip(line).startsWith('╭')).toBe(true)
      expect(strip(line).endsWith('╮')).toBe(true)
    })

    it('keeps exact width for CJK titles', () => {
      const line = boxTitleLine('自由草稿详情', { width: 36 })
      expect(getStringWidth(strip(line))).toBe(36)
    })

    it('centers the title when align=center', () => {
      const line = boxTitleLine('AB', { width: 20, align: 'center' })
      const plain = strip(line)
      expect(getStringWidth(plain)).toBe(20)
      const idx = plain.indexOf('AB')
      expect(plain.slice(0, idx).replace(/[╭─ ]/g, '').length).toBe(0)
    })

    it('truncates long titles instead of breaking the border', () => {
      const line = boxTitleLine('a very long title that overflows the box', { width: 24 })
      expect(getStringWidth(strip(line))).toBe(24)
    })
  })

  describe('writeBoxTitle', () => {
    it('writes the title line through the writer callback', () => {
      const lines: string[] = []
      writeBoxTitle((l) => lines.push(l), 'T', { width: 12 })
      expect(lines).toHaveLength(1)
      expect(getStringWidth(strip(lines[0]))).toBe(12)
    })
  })

  describe('boxLine / boxBottom / hr', () => {
    it('prefixes content with a left border', () => {
      expect(strip(boxLine('hello'))).toBe('│ hello')
      expect(strip(boxLine())).toBe('│')
    })

    it('renders the bottom border at exact width', () => {
      const bottom = strip(boxBottom(40))
      expect(bottom.startsWith('╰')).toBe(true)
      expect(bottom.endsWith('╯')).toBe(true)
      expect(getStringWidth(bottom)).toBe(40)
    })

    it('renders a dim separator of the given width', () => {
      expect(strip(hr(20))).toBe('─'.repeat(20))
    })
  })

  describe('kvLine', () => {
    it('aligns the value column for CJK labels', () => {
      const a = kvLine('草稿ID', 'v1', { labelWidth: 8 })
      const b = kvLine('标题', 'v2', { labelWidth: 8 })
      expect(strip(a)).toBe('草稿ID  : v1')
      expect(strip(b)).toBe('标题    : v2')
    })

    it('colors the value only when valueColor is given', () => {
      expect(kvLine('k', 'v', { valueColor: ANSI.BRIGHT_GREEN })).toContain(`${ANSI.BRIGHT_GREEN}v${ANSI.RESET}`)
      expect(kvLine('k', `${ANSI.RED}v${ANSI.RESET}`)).not.toContain(ANSI.BRIGHT_GREEN)
    })
  })

  describe('wrapDisplay', () => {
    it('wraps CJK text by display width', () => {
      expect(wrapDisplay('一二三四五六七八九十', 8)).toEqual(['一二三四', '五六七八', '九十'])
    })

    it('hard-breaks overlong English words', () => {
      const lines = wrapDisplay('supercalifragilistic', 8)
      expect(lines).toEqual(['supercal', 'ifragili', 'stic'])
      for (const l of lines) expect(getStringWidth(l)).toBeLessThanOrEqual(8)
    })

    it('prefers breaking Latin text at spaces', () => {
      expect(wrapDisplay('hello world foo', 10)).toEqual(['hello', 'world foo'])
    })

    it('preserves paragraphs and empty lines', () => {
      expect(wrapDisplay('ab\n\ncd', 10)).toEqual(['ab', '', 'cd'])
    })

    it('applies hanging indent to continuation lines within the width', () => {
      const lines = wrapDisplay('one two three four five', 10, { hangingIndent: 2 })
      expect(lines).toEqual(['one two', '  three', '  four', '  five'])
      for (const l of lines) expect(getStringWidth(l)).toBeLessThanOrEqual(10)
    })

    it('keeps mixed CJK/Latin lines within the width', () => {
      const lines = wrapDisplay('这是一篇 about 旅行的小红书笔记草稿 body 文本', 16)
      expect(lines.length).toBeGreaterThan(1)
      for (const l of lines) expect(getStringWidth(l)).toBeLessThanOrEqual(16)
    })
  })
  describe('badge', () => {
    it('wraps text in brackets with the given color', () => {
      const b = badge('已发布', ANSI.BRIGHT_CYAN)
      expect(strip(b)).toBe('[已发布]')
      expect(b).toContain(ANSI.BRIGHT_CYAN)
    })
  })

  describe('writeEmptyState', () => {
    it('renders centered icon/title/hint rows inside box borders', () => {
      const lines: string[] = []
      writeEmptyState((l) => lines.push(l), { width: 40, icon: '✨', title: 'No drafts yet', hint: 'Type to create' })
      const plain = lines.map(strip)
      // blank / icon / title / hint / blank — all with the left card border
      expect(plain).toHaveLength(5)
      for (const l of plain) expect(l.startsWith('│')).toBe(true)
      expect(plain[1]).toContain('✨')
      expect(plain[2]).toContain('No drafts yet')
      expect(plain[3]).toContain('Type to create')
      // centered: title row has leading spaces before the text
      expect(plain[2].indexOf('No drafts yet')).toBeGreaterThan(2)
    })

    it('omits icon and hint rows when not given', () => {
      const lines: string[] = []
      writeEmptyState((l) => lines.push(l), { width: 36, title: '空' })
      expect(lines.map(strip)).toHaveLength(3)
    })

    it('centers double-width pictographic icons by their real cell width', () => {
      const lines: string[] = []
      // width 39: ✨ renders as 2 cells, so pad = floor((39-2-2)/2) = 17,
      // icon index = 2 ("│ ") + 17. Measured as width 1 it would sit at 20.
      writeEmptyState((l) => lines.push(l), { width: 39, icon: '✨', title: 'x' })
      expect(strip(lines[1]).indexOf('✨')).toBe(19)
    })

    it('truncates overlong title/hint to the card width', () => {
      const lines: string[] = []
      writeEmptyState((l) => lines.push(l), { width: 36, title: 'x'.repeat(100) })
      expect(getStringWidth(strip(lines[1]))).toBeLessThanOrEqual(36)
    })
  })

  describe('writeError', () => {
    it('renders a red ✗ mark with a bright-red message', () => {
      const lines: string[] = []
      writeError((l) => lines.push(l), 'fetch failed')
      expect(lines).toHaveLength(1)
      expect(strip(lines[0])).toBe('✗ fetch failed')
      expect(lines[0]).toContain(ANSI.RED)
      expect(lines[0]).toContain(ANSI.BRIGHT_RED)
    })

    it('renders the optional dim hint on a second line', () => {
      const lines: string[] = []
      writeError((l) => lines.push(l), 'failed', 'try /publish first')
      expect(lines).toHaveLength(2)
      expect(strip(lines[1])).toBe('  try /publish first')
      expect(lines[1]).toContain(ANSI.DIM)
    })
  })
})
