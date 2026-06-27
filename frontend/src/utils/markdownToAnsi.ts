/**
 * markdownToAnsi — lightweight Markdown → ANSI conversion for xterm.js.
 *
 * Handles: bold, italic, code, code blocks, headings, lists, links.
 * Does NOT handle: tables, blockquotes, HTML tags.
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
const BRIGHT_GREEN = ESC + '92m'
const BRIGHT_YELLOW = ESC + '93m'
const BRIGHT_CYAN = ESC + '96m'
const BRIGHT_BLUE = ESC + '94m'

export function markdownToAnsi(md: string): string {
  if (!md) return ''
  let out = md

  // Code blocks: ```lang ... ```  → cyan block with markers
  out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const header = lang ? `${BRIGHT_CYAN}┌─ ${lang} ${RESET}` : `${BRIGHT_CYAN}┌──${RESET}`
    const lines = code.trimEnd().split('\n').map((l: string) => `${CYAN}│ ${l}${RESET}`)
    const footer = `${BRIGHT_CYAN}└──${RESET}`
    return `${header}\n${lines.join('\n')}\n${footer}`
  })

  // Inline code: `text` → cyan
  out = out.replace(/`([^`]+)`/g, `${CYAN}$1${RESET}`)

  // Bold: **text** → bold
  out = out.replace(/\*\*(.+?)\*\*/g, `${BOLD}$1${RESET}`)

  // Italic: *text* → italic (avoid matching inside bold)
  out = out.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, `${ITALIC}$1${RESET}`)

  // Headings: # text → bold underline
  out = out.replace(/^#{1,6}\s+(.+)$/gm, (_, text) => {
    return `${BOLD}${UNDERLINE}${text}${RESET}`
  })

  // Unordered lists: - text → • text
  out = out.replace(/^(\s*)-\s+/gm, '$1• ')

  // Ordered lists: 1. text → 1. text (keep, already looks fine in terminal)

  // Links: [text](url) → underlined blue text + url
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, `${BRIGHT_BLUE}${UNDERLINE}$1${RESET} ${DIM}($2)${RESET}`)

  // Horizontal rules: --- → dim line
  out = out.replace(/^---+$/gm, `${DIM}────────────────────────────────${RESET}`)

  return out
}

/** ANSI color constants for terminal output categories */
export const ANSI = {
  RESET, BOLD, DIM, ITALIC, UNDERLINE,
  CYAN, GREEN, YELLOW, RED, BLUE, MAGENTA, WHITE,
  BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_CYAN, BRIGHT_BLUE,
  ESC,
} as const
