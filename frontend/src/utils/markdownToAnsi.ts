/**
 * markdownToAnsi — lightweight Markdown → ANSI conversion for xterm.js.
 *
 * Handles: bold, italic, code, code blocks, headings, lists, links.
 * Does NOT handle: tables, blockquotes, HTML tags.
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
const BRIGHT_GREEN = ESC + '92m'
const BRIGHT_YELLOW = ESC + '93m'
const BRIGHT_CYAN = ESC + '96m'
const BRIGHT_BLUE = ESC + '94m'
const BRIGHT_MAGENTA = ESC + '95m'
const BRIGHT_WHITE = ESC + '97m'

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

  // Headings: # text → bold + color by level
  out = out.replace(/^(#{1,6})\s+(.+)$/gm, (_, hashes, text) => {
    const level = hashes.length
    const colors = [BRIGHT_MAGENTA, BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_YELLOW, BRIGHT_GREEN, CYAN]
    const color = colors[Math.min(level - 1, colors.length - 1)]
    return `${BOLD}${color}${text}${RESET}`
  })

  // Unordered lists: - text → • text
  out = out.replace(/^(\s*)-\s+/gm, '$1• ')

  // Ordered lists: 1. text — keep as-is

  // Links: [text](url) → underlined blue text + dim url
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, `${BRIGHT_BLUE}${UNDERLINE}$1${RESET} ${DIM}($2)${RESET}`)

  // Fullwidth punctuation → ASCII equivalents (terminal CJK rendering fix)
  // ponytail: WebGL renderer can't render fullwidth glyphs; halfwidth is correct for monospace TUI anyway
  const fwMap: Record<string, string> = { '？': '?', '！': '!', '：': ':', '；': ';', '，': ',', '。': '.', '（': '(', '）': ')' }
  out = out.replace(/[？！：；，。（）]/g, (ch) => fwMap[ch] ?? ch)

  // Horizontal rules: --- → dim line (adaptive width)
  const hrWidth = Math.max(20, termCols - 4)
  out = out.replace(/^---+$/gm, `${DIM}${'─'.repeat(hrWidth)}${RESET}`)

  return out
}

/** ANSI color constants for terminal output categories */
export const ANSI = {
  RESET, BOLD, DIM, ITALIC, UNDERLINE,
  CYAN, GREEN, YELLOW, RED, BLUE, MAGENTA, WHITE,
  BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_MAGENTA, BRIGHT_WHITE,
  ESC,
} as const
