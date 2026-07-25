/**
 * markdownToAnsi — lightweight Markdown → ANSI conversion for xterm.js.
 *
 * Handles: bold, italic, code, code blocks, headings, lists, links, blockquotes.
 * Does NOT handle: tables, HTML tags.
 * Designed for Tokyo Night terminal palette.
 */
// ponytail: regex-based, no AST — covers 95% of AI output patterns

const ESC = '\x1b['
const RESET = ESC + '0m'
const BOLD = ESC + '1m'
const DIM = ESC + '2m'
const ITALIC = ESC + '3m'
const UNDERLINE = ESC + '4m'
const CYAN = ESC + '36m'
const GREEN = ESC + '32m'
const YELLOW = ESC + '33m'
const RED = ESC + '31m'
const BLUE = ESC + '34m'
const MAGENTA = ESC + '35m'
const WHITE = ESC + '37m'
const BRIGHT_RED = ESC + '91m'
const BRIGHT_GREEN = ESC + '92m'
const BRIGHT_YELLOW = ESC + '93m'
const BRIGHT_CYAN = ESC + '96m'
const BRIGHT_BLUE = ESC + '94m'
const BRIGHT_MAGENTA = ESC + '95m'
const BRIGHT_WHITE = ESC + '97m'

// Inline wcwidth — avoids relying on experimental term.unicode API.
// CJK ideographs, fullwidth forms, Hangul, etc. count as width 2.
// Lives here (not ansiCards) so heading rules can measure text without a
// circular import; ansiCards re-exports it.
export function getStringWidth(str: string): number {
  let width = 0
  for (const char of str) {
    const code = char.codePointAt(0)!
    if (code >= 0x1100 && (
      code <= 0x115F ||
      code === 0x2329 || code === 0x232A ||
      (code >= 0x2E80 && code <= 0xA4CF && code !== 0x303F) ||
      (code >= 0xAC00 && code <= 0xD7A3) ||
      (code >= 0xF900 && code <= 0xFAFF) ||
      (code >= 0xFE10 && code <= 0xFE19) ||
      (code >= 0xFE30 && code <= 0xFE6F) ||
      (code >= 0xFF01 && code <= 0xFF60) ||
      (code >= 0xFFE0 && code <= 0xFFE6) ||
      (code >= 0x20000 && code <= 0x2FFFD) ||
      (code >= 0x30000 && code <= 0x3FFFD)
    )) {
      width += 2
    } else {
      width += 1
    }
  }
  return width
}

/** Strip SGR sequences so display width can be measured on styled text. */
function stripAnsi(str: string): string {
  return str.replace(/\x1b\[[0-9;]*m/g, '')
}

export function markdownToAnsi(md: string, termCols = 80): string {
  if (!md) return ''
  let out = md

  // Code blocks: ```lang ... ```  → styled block with box drawing
  // ponytail: adaptive width based on terminal columns, not hardcoded 36
  out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const innerWidth = Math.max(20, termCols - 4) // 4 = "│ " + " │" borders
    const headerText = lang ? `─ ${lang} ${'─'.repeat(Math.max(1, innerWidth - lang.length - 3))}` : '─'.repeat(innerWidth)
    const header = `${BRIGHT_CYAN}╭${headerText}╮${RESET}`
    const lines = code.trimEnd().split('\n').map((l: string) => `${DIM}│${RESET} ${l}`)
    const footer = `${BRIGHT_CYAN}╰${'─'.repeat(innerWidth)}╯${RESET}`
    return `${header}\n${lines.join('\n')}\n${footer}`
  })

  // Inline code: `text` → cyan
  out = out.replace(/`([^`]+)`/g, `${CYAN}$1${RESET}`)

  // Bold: **text** → bold bright white
  out = out.replace(/\*\*(.+?)\*\*/g, `${BOLD}${BRIGHT_WHITE}$1${RESET}`)

  // Italic: *text* → italic (avoid matching inside bold)
  out = out.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, `${ITALIC}$1${RESET}`)

  // Headings: # text → bold + color by level; H1 also gets a dim rule below
  // so it separates clearly from body text
  out = out.replace(/^(#{1,6})\s+(.+)$/gm, (_, hashes, text) => {
    const level = hashes.length
    const colors = [BRIGHT_MAGENTA, BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_YELLOW, BRIGHT_GREEN, CYAN]
    const color = colors[Math.min(level - 1, colors.length - 1)]
    if (level === 1) {
      const ruleW = Math.max(4, Math.min(getStringWidth(stripAnsi(text)), termCols - 4))
      return `${BOLD}${color}${text}${RESET}\n${DIM}${'─'.repeat(ruleW)}${RESET}`
    }
    return `${BOLD}${color}${text}${RESET}`
  })

  // Unordered lists: - text → bright-cyan bullet
  out = out.replace(/^(\s*)-\s+/gm, `$1${BRIGHT_CYAN}•${RESET} `)

  // Ordered lists: 1. text → bright-yellow number
  out = out.replace(/^(\s*)(\d+)\.(\s+)/gm, `$1${BRIGHT_YELLOW}$2.${RESET}$3`)

  // Blockquotes: > text → dim vertical bar + dim italic text
  out = out.replace(/^>\s?(.*)$/gm, `${DIM}│${RESET} ${DIM}${ITALIC}$1${RESET}`)

  // Links: [text](url) → underlined blue text + dim url
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, `${BRIGHT_BLUE}${UNDERLINE}$1${RESET} ${DIM}($2)${RESET}`)

  // Horizontal rules: --- → dim line (adaptive width)
  const hrWidth = Math.max(20, termCols - 4)
  out = out.replace(/^---+$/gm, `${DIM}${'─'.repeat(hrWidth)}${RESET}`)

  return out
}

/** ANSI color constants for terminal output categories */
export const ANSI = {
  RESET, BOLD, DIM, ITALIC, UNDERLINE,
  CYAN, GREEN, YELLOW, RED, BLUE, MAGENTA, WHITE,
  BRIGHT_RED, BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_MAGENTA, BRIGHT_WHITE,
  ESC,
} as const
