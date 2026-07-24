// frontend/tests/utils/markdownToAnsi.spec.ts
import { describe, it, expect } from 'vitest'
import { markdownToAnsi, ANSI } from '@/utils/markdownToAnsi'

describe('markdownToAnsi', () => {
  it('renders blockquotes as a dim bar with dim italic text', () => {
    const out = markdownToAnsi('> quoted text')
    expect(out).toContain(`${ANSI.DIM}│${ANSI.RESET}`)
    expect(out).toContain(`${ANSI.DIM}${ANSI.ITALIC}quoted text${ANSI.RESET}`)
  })

  it('colors unordered list bullets bright cyan', () => {
    const out = markdownToAnsi('- item one')
    expect(out).toContain(`${ANSI.BRIGHT_CYAN}•${ANSI.RESET} item one`)
  })

  it('colors ordered list numbers bright yellow', () => {
    const out = markdownToAnsi('1. first\n2. second')
    expect(out).toContain(`${ANSI.BRIGHT_YELLOW}1.${ANSI.RESET} first`)
    expect(out).toContain(`${ANSI.BRIGHT_YELLOW}2.${ANSI.RESET} second`)
  })

  it('adds a dim rule under level-1 headings only', () => {
    const h1 = markdownToAnsi('# Title')
    const lines = h1.split('\n')
    expect(lines[0]).toBe(`${ANSI.BOLD}${ANSI.BRIGHT_MAGENTA}Title${ANSI.RESET}`)
    expect(lines[1]).toBe(`${ANSI.DIM}${'─'.repeat(5)}${ANSI.RESET}`)
    // h2+ keeps the single-line rendering
    expect(markdownToAnsi('## Sub').split('\n')).toHaveLength(1)
  })

  it('does not apply list/quote rules inside code blocks', () => {
    const out = markdownToAnsi('```\n1. not a list\n- not a bullet\n> not a quote\n```')
    expect(out).toContain('1. not a list')
    expect(out).toContain('- not a bullet')
    expect(out).toContain('> not a quote')
    expect(out).not.toContain(`${ANSI.BRIGHT_YELLOW}1.${ANSI.RESET}`)
    expect(out).not.toContain('•')
    expect(out).not.toContain(ANSI.ITALIC)
  })

  it('keeps code block box rendering (regression)', () => {
    const out = markdownToAnsi('```js\nconst a = 1\n```')
    expect(out).toContain(`${ANSI.BRIGHT_CYAN}╭`)
    expect(out).toContain('const a = 1')
    expect(out).toContain(`${ANSI.BRIGHT_CYAN}╰`)
  })

  it('keeps bold and inline code working (regression)', () => {
    expect(markdownToAnsi('**bold**')).toContain(`${ANSI.BOLD}${ANSI.BRIGHT_WHITE}bold${ANSI.RESET}`)
    expect(markdownToAnsi('`code`')).toContain(`${ANSI.CYAN}code${ANSI.RESET}`)
  })

  it('keeps fullwidth punctuation conversion (regression)', () => {
    expect(markdownToAnsi('你好？世界！')).toBe('你好?世界!')
  })
})
